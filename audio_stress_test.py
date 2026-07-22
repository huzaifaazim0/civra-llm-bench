#!/usr/bin/env python3
"""
Concurrent audio stress client for OpenAI-compatible multimodal / Omni servers.

Modes:
  audio_to_text  — audio in, text out (modalities=["text"] when supported)
  audio_to_audio — audio in, audio(+text) out; optionally writes WAVs to --gallery-dir
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import statistics
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


@dataclass
class RequestResult:
    id: int
    ok: bool
    error: str | None
    label: str
    ttft_ms: float | None
    total_ms: float | None
    text: str | None
    audio_path: str | None
    audio_bytes: int
    audio_duration_sec: float | None
    rtf: float | None  # audio_duration / wall_sec


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def load_wav_b64(path: Path) -> tuple[str, float]:
    raw = path.read_bytes()
    duration = 0.0
    try:
        with wave.open(str(path), "rb") as w:
            duration = w.getnframes() / float(w.getframerate())
    except wave.Error:
        duration = 0.0
    return base64.b64encode(raw).decode("ascii"), duration


def decode_audio_payload(payload: Any) -> bytes | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("b64_json") or payload.get("audio")
        if isinstance(data, str):
            return base64.b64decode(data)
        return None
    if isinstance(payload, str):
        # Sometimes returned as data URL
        if payload.startswith("data:"):
            payload = payload.split(",", 1)[-1]
        try:
            return base64.b64decode(payload)
        except Exception:
            return None
    return None


def wav_duration_from_bytes(data: bytes) -> float | None:
    try:
        import io

        with wave.open(io.BytesIO(data), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return None


def build_messages(audio_b64: str, instruction: str) -> list[dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {"data": audio_b64, "format": "wav"},
                },
                {"type": "text", "text": instruction},
            ],
        }
    ]


async def one_request(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    req_id: int,
    label: str,
    wav_path: Path,
    instruction: str,
    mode: str,
    max_tokens: int,
    temperature: float,
    gallery_dir: Path | None,
    voice: str | None,
) -> RequestResult:
    audio_b64, _in_dur = load_wav_b64(wav_path)
    body: dict[str, Any] = {
        "model": model,
        "messages": build_messages(audio_b64, instruction),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if mode == "audio_to_text":
        body["modalities"] = ["text"]
    else:
        body["modalities"] = ["text", "audio"]
        if voice:
            body["audio"] = {"voice": voice, "format": "wav"}

    t0 = time.perf_counter()
    ttft_ms: float | None = None
    try:
        r = await client.post(f"{base_url}/v1/chat/completions", json=body, timeout=300.0)
        ttft_ms = (time.perf_counter() - t0) * 1000.0  # non-stream: approx first payload
        total_ms = (time.perf_counter() - t0) * 1000.0
        if r.status_code >= 400:
            return RequestResult(
                req_id, False, f"HTTP {r.status_code}: {r.text[:400]}", label,
                ttft_ms, total_ms, None, None, 0, None, None,
            )
        data = r.json()
        choices = data.get("choices") or []
        text_parts: list[str] = []
        audio_bytes = b""
        for ch in choices:
            msg = ch.get("message") or {}
            if msg.get("content"):
                text_parts.append(str(msg["content"]))
            audio_obj = msg.get("audio")
            decoded = decode_audio_payload(audio_obj)
            if decoded:
                audio_bytes = decoded
        # Some servers put audio in a second choice
        text = "\n".join(t for t in text_parts if t).strip() or None
        out_path: str | None = None
        audio_dur: float | None = None
        rtf: float | None = None
        if audio_bytes and gallery_dir is not None:
            gallery_dir.mkdir(parents=True, exist_ok=True)
            voice_tag = voice or "default"
            fname = f"aa_{label}_{voice_tag}_{req_id:03d}.wav"
            path = gallery_dir / fname
            path.write_bytes(audio_bytes)
            out_path = str(path)
            audio_dur = wav_duration_from_bytes(audio_bytes)
            wall_s = total_ms / 1000.0
            if audio_dur and wall_s > 0:
                rtf = audio_dur / wall_s
            side = path.with_suffix(".txt")
            side.write_text(
                f"label={label}\nvoice={voice_tag}\ninput={wav_path.name}\n"
                f"wall_ms={total_ms:.1f}\naudio_duration_sec={audio_dur}\n"
                f"rtf={rtf}\n\nTEXT:\n{text or ''}\n",
                encoding="utf-8",
            )
        return RequestResult(
            req_id, True, None, label, ttft_ms, total_ms, text, out_path,
            len(audio_bytes), audio_dur, rtf,
        )
    except Exception as e:
        total_ms = (time.perf_counter() - t0) * 1000.0
        return RequestResult(
            req_id, False, str(e), label, ttft_ms, total_ms, None, None, 0, None, None,
        )


def summarize(results: list[RequestResult], concurrency: int) -> dict[str, Any]:
    ok = [r for r in results if r.ok]
    fail = [r for r in results if not r.ok]
    ttfts = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    totals = [r.total_ms for r in ok if r.total_ms is not None]
    rtfs = [r.rtf for r in ok if r.rtf is not None]
    return {
        "concurrency": concurrency,
        "total_requests": len(results),
        "ok": len(ok),
        "failed": len(fail),
        "error_rate_percent": round(100.0 * len(fail) / max(1, len(results)), 2),
        "ttft_avg_ms": round(statistics.mean(ttfts), 2) if ttfts else None,
        "ttft_p50_ms": round(pct(ttfts, 50), 2) if ttfts else None,
        "ttft_p95_ms": round(pct(ttfts, 95), 2) if ttfts else None,
        "total_avg_ms": round(statistics.mean(totals), 2) if totals else None,
        "total_p95_ms": round(pct(totals, 95), 2) if totals else None,
        "rtf_avg": round(statistics.mean(rtfs), 3) if rtfs else None,
        "rtf_p50": round(pct(rtfs, 50), 3) if rtfs else None,
        "sample_errors": [r.error for r in fail[:5]],
        "sample_texts": [r.text for r in ok[:3] if r.text],
        "gallery_files": [r.audio_path for r in ok if r.audio_path],
    }


async def run_batch(
    *,
    base_url: str,
    model: str,
    mode: str,
    fixtures: list[tuple[str, Path]],
    concurrency: int,
    requests: int,
    instruction: str,
    max_tokens: int,
    temperature: float,
    gallery_dir: Path | None,
    voice: str | None,
) -> dict[str, Any]:
    assert fixtures, "no audio fixtures"
    limits = httpx.Limits(max_connections=max(concurrency, 8), max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(limits=limits) as client:
        sem = asyncio.Semaphore(concurrency)

        async def wrapped(i: int) -> RequestResult:
            label, path = fixtures[i % len(fixtures)]
            async with sem:
                return await one_request(
                    client,
                    base_url=base_url,
                    model=model,
                    req_id=i,
                    label=label,
                    wav_path=path,
                    instruction=instruction,
                    mode=mode,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    gallery_dir=gallery_dir,
                    voice=voice,
                )

        t0 = time.perf_counter()
        results = await asyncio.gather(*[wrapped(i) for i in range(requests)])
        duration = time.perf_counter() - t0
    summary = summarize(list(results), concurrency)
    summary["duration_sec"] = round(duration, 2)
    summary["mode"] = mode
    summary["model"] = model
    summary["base_url"] = base_url
    summary["voice"] = voice
    return summary


def discover_fixtures(fixtures_dir: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for p in sorted(fixtures_dir.glob("in_*.wav")):
        label = p.stem.removeprefix("in_")
        out.append((label, p))
    return out


def write_listen_me(gallery_dir: Path, entries: list[dict[str, Any]]) -> None:
    lines = [
        "# Omni audio→audio listen gallery",
        "",
        "Play the `.wav` files below. Matching `.txt` has transcript + timing.",
        "",
        "| File | Label | Voice | Duration (s) | Wall (ms) | RTF |",
        "|------|-------|-------|-------------:|----------:|----:|",
    ]
    for e in entries:
        lines.append(
            f"| `{e.get('file','')}` | {e.get('label','')} | {e.get('voice','')} | "
            f"{e.get('audio_duration_sec','')} | {e.get('wall_ms','')} | {e.get('rtf','')} |"
        )
    (gallery_dir / "LISTEN_ME.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_gallery(
    *,
    base_url: str,
    model: str,
    fixtures_dir: Path,
    gallery_dir: Path,
    instruction: str,
    max_tokens: int,
    temperature: float,
    voices: list[str | None],
) -> dict[str, Any]:
    fixtures = discover_fixtures(fixtures_dir)
    # Prefer curated labels for quality review
    prefer = [
        "greeting", "medicare_explain", "clarify_zip", "empathy",
        "repeat_back", "longform", "rephrase_short", "status_update",
    ]
    ordered = []
    by_label = {l: p for l, p in fixtures}
    for lab in prefer:
        if lab in by_label:
            ordered.append((lab, by_label[lab]))
    for lab, p in fixtures:
        if lab not in {x[0] for x in ordered}:
            ordered.append((lab, p))

    gallery_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    results_meta: list[dict[str, Any]] = []
    req_id = 0
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=4)
    async with httpx.AsyncClient(limits=limits) as client:
        for voice in voices:
            for label, path in ordered:
                r = await one_request(
                    client,
                    base_url=base_url,
                    model=model,
                    req_id=req_id,
                    label=label,
                    wav_path=path,
                    instruction=instruction,
                    mode="audio_to_audio",
                    max_tokens=max_tokens,
                    temperature=temperature,
                    gallery_dir=gallery_dir,
                    voice=voice,
                )
                req_id += 1
                results_meta.append(asdict(r))
                if r.ok and r.audio_path:
                    entries.append(
                        {
                            "file": Path(r.audio_path).name,
                            "label": label,
                            "voice": voice or "default",
                            "audio_duration_sec": r.audio_duration_sec,
                            "wall_ms": round(r.total_ms or 0, 1),
                            "rtf": r.rtf,
                            "ok": True,
                        }
                    )
                else:
                    entries.append(
                        {
                            "file": "",
                            "label": label,
                            "voice": voice or "default",
                            "audio_duration_sec": None,
                            "wall_ms": round(r.total_ms or 0, 1),
                            "rtf": None,
                            "ok": False,
                            "error": r.error,
                        }
                    )
                print(
                    f"gallery voice={voice or 'default'} label={label} "
                    f"ok={r.ok} wall_ms={r.total_ms} err={r.error}"
                )
    write_listen_me(gallery_dir, [e for e in entries if e.get("ok")])
    return {
        "mode": "audio_to_audio_gallery",
        "model": model,
        "gallery_dir": str(gallery_dir),
        "entries": entries,
        "results": results_meta,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--model", required=True)
    ap.add_argument(
        "--mode",
        choices=["audio_to_text", "audio_to_audio", "gallery"],
        required=True,
    )
    ap.add_argument("--fixtures-dir", default="/root/.cvr/llm_stress_test/gpu/fixtures")
    ap.add_argument("--gallery-dir", default="/root/.cvr/llm_stress_test/gpu/omni_listen_gallery")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--requests", type=int, default=0, help="0 = same as concurrency")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--temperature", type=float, default=0.4)
    ap.add_argument(
        "--instruction",
        default=(
            "Listen to the caller audio and respond helpfully as a clear spoken phone agent. "
            "Be concise."
        ),
    )
    ap.add_argument("--voice", default=None, help="Single voice for stress mode")
    ap.add_argument(
        "--voices",
        default="Chelsie,Ethan",
        help="Comma-separated voices for gallery mode (empty = default only)",
    )
    ap.add_argument("--output", required=True)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--sweep-start", type=int, default=1)
    ap.add_argument("--sweep-max", type=int, default=20)
    ap.add_argument("--sweep-step", type=int, default=1)
    ap.add_argument("--stop-ttft-ms", type=float, default=3000.0)
    args = ap.parse_args()

    fixtures_dir = Path(args.fixtures_dir)
    gallery_dir = Path(args.gallery_dir) if args.mode in ("audio_to_audio", "gallery") else None
    fixtures = discover_fixtures(fixtures_dir)
    if not fixtures:
        raise SystemExit(f"No in_*.wav fixtures in {fixtures_dir}")

    if args.mode == "gallery":
        voices_raw = [v.strip() for v in args.voices.split(",") if v.strip()]
        voices: list[str | None] = voices_raw or [None]
        out = asyncio.run(
            run_gallery(
                base_url=args.base_url.rstrip("/"),
                model=args.model,
                fixtures_dir=fixtures_dir,
                gallery_dir=Path(args.gallery_dir),
                instruction=args.instruction,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                voices=voices,
            )
        )
        Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps({"gallery_dir": out["gallery_dir"], "n": len(out["entries"])}, indent=2))
        print(f"Wrote {args.output}")
        return

    async def stress_one(c: int) -> dict[str, Any]:
        n = args.requests or c
        return await run_batch(
            base_url=args.base_url.rstrip("/"),
            model=args.model,
            mode=args.mode,
            fixtures=fixtures,
            concurrency=c,
            requests=n,
            instruction=args.instruction,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            gallery_dir=gallery_dir if args.mode == "audio_to_audio" else None,
            voice=args.voice,
        )

    if args.sweep:
        levels = []
        max_stable = 0
        limit_hit = None
        stop_reason = None
        for c in range(args.sweep_start, args.sweep_max + 1, args.sweep_step):
            print(f">>> concurrency={c}")
            s = asyncio.run(stress_one(c))
            levels.append(s)
            print(
                f"c={c} ok={s['ok']}/{s['total_requests']} "
                f"ttft_p95={s.get('ttft_p95_ms')} total_p95={s.get('total_p95_ms')} "
                f"err%={s['error_rate_percent']}"
            )
            ttft = s.get("ttft_p95_ms")
            if s["failed"] > 0 or (ttft is not None and ttft > args.stop_ttft_ms):
                limit_hit = c
                stop_reason = (
                    f"errors={s['failed']}" if s["failed"] else f"ttft_p95={ttft}>{args.stop_ttft_ms}"
                )
                break
            max_stable = c
        out = {
            "mode": f"{args.mode}_sweep",
            "model": args.model,
            "max_stable_concurrency": max_stable,
            "limit_hit_at": limit_hit,
            "stop_reason": stop_reason,
            "levels": levels,
        }
    else:
        out = asyncio.run(stress_one(args.concurrency))

    Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out if not args.sweep else {
        "max_stable_concurrency": out["max_stable_concurrency"],
        "limit_hit_at": out["limit_hit_at"],
        "stop_reason": out["stop_reason"],
    }, indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
