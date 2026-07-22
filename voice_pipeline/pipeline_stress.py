#!/usr/bin/env python3
"""Voice pipeline stress: STT → LLM (stream) → TTS (sentence stream) with concurrency ramp."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from adapters import StageTimings, pct, split_sentences  # noqa: E402
from adapters.llm_vllm import VLLMLLM  # noqa: E402
from adapters.stt_ifw import IFWSTT  # noqa: E402
from adapters.stt_parakeet import ParakeetSTT  # noqa: E402
from adapters.tts_kokoro import KokoroTTS  # noqa: E402
from adapters.tts_melo import MeloTTS  # noqa: E402
from adapters.tts_neutts import NeuTTSTTS  # noqa: E402

LLM_MAP = {
    "moe": "QuixiAI/Qwen3-30B-A3B-AWQ",
    "3b": "Qwen/Qwen2.5-3B-Instruct",
    "7b": "Qwen/Qwen2.5-7B-Instruct",
}


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v


def gpu_snapshot() -> dict[str, Any]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
        gpus = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                gpus.append(
                    {
                        "index": int(parts[0]),
                        "name": parts[1],
                        "util_pct": float(parts[2]),
                        "mem_used_mb": float(parts[3]),
                        "mem_total_mb": float(parts[4]),
                    }
                )
        return {"gpus": gpus}
    except Exception as exc:
        return {"error": str(exc)}


def vram_placement(llm_key: str, stt_name: str, tts_name: str) -> dict[str, Any]:
    """Honest stage placement for 1×20GB Ada."""
    moe = llm_key == "moe"
    if moe:
        stt_dev = "cpu" if stt_name == "ifw" else "server_cpu"
        tts_dev = {
            "kokoro": "server_cpu",
            "melo": "cpu",
            "neutts": "cpu",
        }[tts_name]
        note = "MoE exclusive GPU; Parakeet/Kokoro forced to CPU servers; IFW/Melo/NeuTTS on CPU"
    else:
        stt_dev = "cuda" if stt_name == "ifw" else "server_gpu"
        tts_dev = "server_gpu" if tts_name == "kokoro" else ("cuda" if tts_name == "melo" else "gpu")
        note = "3B/7B allow co-residency if free VRAM permits"
    return {
        "llm": "gpu",
        "stt": stt_dev,
        "tts": tts_dev,
        "moe_exclusive": moe,
        "note": note,
    }


def build_stt(name: str, llm_key: str):
    if name == "parakeet":
        return ParakeetSTT(
            base=os.environ.get("PARAKEET_BASE", "http://127.0.0.1:37283"),
            ws_url=os.environ.get("PARAKEET_WS"),
        )
    if name == "ifw":
        device = os.environ.get("IFW_DEVICE", "cuda")
        if llm_key == "moe":
            device = os.environ.get("IFW_DEVICE_MOE", "cpu")
        return IFWSTT(device=device)
    raise SystemExit(f"unknown stt: {name}")


def build_tts(name: str, llm_key: str):
    if name == "kokoro":
        return KokoroTTS()
    if name == "melo":
        device = os.environ.get("MELO_DEVICE", "cuda")
        if llm_key == "moe":
            device = os.environ.get("MELO_DEVICE_MOE", "cpu")
        return MeloTTS(device=device)
    if name == "neutts":
        backbone_device = os.environ.get("NEUTTS_BACKBONE_DEVICE", "gpu")
        if llm_key == "moe":
            backbone_device = os.environ.get("NEUTTS_BACKBONE_DEVICE_MOE", "cpu")
            # llama-cpp may still touch CUDA even with n_gpu_layers=0 when the
            # GPU is full of MoE weights — hide the device for CPU-only mode.
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        return NeuTTSTTS(backbone_device=backbone_device)
    raise SystemExit(f"unknown tts: {name}")


def list_fixtures(fixtures_dir: Path) -> list[Path]:
    wavs = sorted(fixtures_dir.glob("in_*.wav"))
    if not wavs:
        wavs = sorted(fixtures_dir.glob("*.wav"))
    if not wavs:
        raise SystemExit(f"no wav fixtures in {fixtures_dir}")
    return wavs


async def run_one_call(
    stt,
    llm: VLLMLLM,
    tts,
    wav_path: Path,
    *,
    use_stt_ws: bool = True,
) -> StageTimings:
    timings = StageTimings()
    t_call = time.perf_counter()
    try:
        if use_stt_ws and getattr(stt, "streaming", False):
            text, stt_ms, partial_ms, meta = await stt.transcribe_ws(wav_path)
            timings.stt_partial_ms = partial_ms
            timings.meta["stt"] = meta
        else:
            text, stt_ms, meta = await stt.transcribe(wav_path)
            timings.meta["stt"] = meta
        timings.stt_ms = stt_ms
        timings.transcript = text
        if not text:
            raise RuntimeError("empty transcript")

        buf = ""
        reply_parts: list[str] = []
        token_count = 0
        llm_t0 = time.perf_counter()
        first_audio = False
        tts_audio_bytes = 0
        tts_wall0: float | None = None

        async def synth_sentence(sentence: str) -> None:
            nonlocal first_audio, tts_audio_bytes, tts_wall0
            if tts_wall0 is None:
                tts_wall0 = time.perf_counter()
            async for chunk, meta in tts.synthesize_stream(sentence):
                tts_audio_bytes += len(chunk)
                if not first_audio:
                    first_audio = True
                    now = time.perf_counter()
                    timings.tts_ttfa_ms = meta.get("ttfa_ms")
                    if timings.tts_ttfa_ms is None and tts_wall0 is not None:
                        timings.tts_ttfa_ms = (now - tts_wall0) * 1000.0
                    timings.e2e_ttfa_ms = (now - t_call) * 1000.0

        async for delta, meta in llm.stream_chat(text):
            if timings.llm_ttft_ms is None and "ttft_ms" in meta:
                timings.llm_ttft_ms = meta["ttft_ms"]
            token_count += 1
            buf += delta
            reply_parts.append(delta)
            sentences, buf = split_sentences(buf)
            for sent in sentences:
                await synth_sentence(sent)

        leftover = buf.strip()
        if leftover:
            await synth_sentence(leftover)
        if not reply_parts:
            await synth_sentence("I'm here to help.")

        timings.llm_total_ms = (time.perf_counter() - llm_t0) * 1000.0
        timings.llm_tokens = token_count
        timings.reply_text = "".join(reply_parts).strip()
        timings.audio_bytes = tts_audio_bytes
        if tts_wall0 is not None:
            timings.tts_total_ms = (time.perf_counter() - tts_wall0) * 1000.0
        timings.e2e_total_ms = (time.perf_counter() - t_call) * 1000.0
        timings.ok = first_audio and bool(timings.transcript)
        if not first_audio:
            timings.error = "no_audio"
            timings.ok = False
    except Exception as exc:
        timings.error = f"{type(exc).__name__}: {exc}"
        timings.ok = False
        timings.e2e_total_ms = (time.perf_counter() - t_call) * 1000.0
    return timings


async def run_wave(
    stt,
    llm: VLLMLLM,
    tts,
    fixtures: list[Path],
    concurrency: int,
    *,
    use_stt_ws: bool,
) -> list[StageTimings]:
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int) -> StageTimings:
        wav = fixtures[i % len(fixtures)]
        async with sem:
            return await run_one_call(stt, llm, tts, wav, use_stt_ws=use_stt_ws)

    return list(await asyncio.gather(*[one(i) for i in range(concurrency)]))


def summarize(results: list[StageTimings], concurrency: int) -> dict[str, Any]:
    oks = [r for r in results if r.ok]
    errs = [r for r in results if not r.ok]

    def col(attr: str) -> list[float]:
        return [float(getattr(r, attr)) for r in oks if getattr(r, attr) is not None]

    e2e = col("e2e_ttfa_ms")
    return {
        "concurrency": concurrency,
        "n": len(results),
        "ok": len(oks),
        "errors": len(errs),
        "error_rate": (len(errs) / len(results)) if results else 1.0,
        "error_samples": [r.error for r in errs[:5]],
        "e2e_ttfa_p50": pct(e2e, 50),
        "e2e_ttfa_p95": pct(e2e, 95),
        "e2e_ttfa_mean": (sum(e2e) / len(e2e)) if e2e else None,
        "stt_ms_p50": pct(col("stt_ms"), 50),
        "llm_ttft_ms_p50": pct(col("llm_ttft_ms"), 50),
        "tts_ttfa_ms_p50": pct(col("tts_ttfa_ms"), 50),
        "e2e_total_ms_p50": pct(col("e2e_total_ms"), 50),
        "llm_tok_s_mean": (
            sum(
                (r.llm_tokens / (r.llm_total_ms / 1000.0))
                for r in oks
                if r.llm_total_ms and r.llm_total_ms > 0
            )
            / len(oks)
            if oks
            else None
        ),
    }


async def find_limit(
    stt,
    llm: VLLMLLM,
    tts,
    fixtures: list[Path],
    *,
    start: int,
    max_c: int,
    factor: int,
    stop_ttfa_ms: float,
    stop_error_rate: float,
    use_stt_ws: bool,
) -> dict[str, Any]:
    levels: list[dict[str, Any]] = []
    max_stable = 0
    limit_hit_at: int | None = None
    stop_reason: str | None = None
    c = start
    while c <= max_c:
        print(f"  concurrency={c} ...", flush=True)
        t0 = time.perf_counter()
        results = await run_wave(stt, llm, tts, fixtures, c, use_stt_ws=use_stt_ws)
        summary = summarize(results, c)
        summary["wall_s"] = time.perf_counter() - t0
        summary["gpu"] = gpu_snapshot()
        levels.append(summary)
        print(
            f"    ok={summary['ok']}/{summary['n']} "
            f"e2e_ttfa_p95={summary['e2e_ttfa_p95']} "
            f"err_rate={summary['error_rate']:.3f}",
            flush=True,
        )
        failed = False
        if summary["error_rate"] > stop_error_rate:
            failed = True
            stop_reason = f"error_rate>{stop_error_rate}"
        elif summary["e2e_ttfa_p95"] is not None and summary["e2e_ttfa_p95"] > stop_ttfa_ms:
            failed = True
            stop_reason = f"e2e_ttfa_p95>{stop_ttfa_ms}"
        if failed:
            limit_hit_at = c
            break
        max_stable = c
        nxt = c * factor if c > 1 else (2 if factor >= 2 else c + 1)
        if nxt == c:
            nxt = c + 1
        c = nxt

    return {
        "levels": levels,
        "max_stable_concurrency": max_stable,
        "limit_hit_at": limit_hit_at,
        "stop_reason": stop_reason,
    }


def _write_result(args, stt_name, llm_key, tts_name, payload: dict) -> Path:
    out_dir = Path(args.results_dir or os.environ.get("RESULTS_DIR", ROOT / "results"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stt_name}__{llm_key}__{tts_name}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def build_results_md(results_dir: Path) -> Path:
    rows = []
    for p in sorted(results_dir.glob("*__*__*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        levels = data.get("levels") or []
        c1 = next((x for x in levels if x.get("concurrency") == 1), None)
        if not c1 and data.get("summary"):
            c1 = data["summary"]
        rows.append(
            {
                "file": p.name,
                "stt": data.get("stt"),
                "llm": data.get("llm"),
                "tts": data.get("tts"),
                "max_stable": data.get(
                    "max_stable_concurrency",
                    (data.get("summary") or {}).get("concurrency"),
                ),
                "limit_hit_at": data.get("limit_hit_at"),
                "stop_reason": data.get("stop_reason"),
                "e2e_ttfa_p50_c1": (c1 or {}).get("e2e_ttfa_p50"),
                "e2e_ttfa_p95_c1": (c1 or {}).get("e2e_ttfa_p95"),
                "ok": data.get("ok"),
            }
        )

    by_conc = sorted(rows, key=lambda r: (-(r["max_stable"] or -1), r["file"]))
    by_ttfa = sorted(
        rows,
        key=lambda r: (
            r["e2e_ttfa_p50_c1"] is None,
            r["e2e_ttfa_p50_c1"] if r["e2e_ttfa_p50_c1"] is not None else 1e18,
        ),
    )

    def table(rs: list[dict]) -> str:
        lines = [
            "| STT | LLM | TTS | max_stable | e2e_ttfa_p50@1 | e2e_ttfa_p95@1 | stop | ok |",
            "|-----|-----|-----|------------|----------------|----------------|------|----|",
        ]
        for r in rs:
            lines.append(
                f"| {r['stt']} | {r['llm']} | {r['tts']} | {r['max_stable']} | "
                f"{r['e2e_ttfa_p50_c1']} | {r['e2e_ttfa_p95_c1']} | {r['stop_reason']} | {r['ok']} |"
            )
        return "\n".join(lines)

    md = (
        "# Voice pipeline stress results\n\n"
        f"Generated from `{results_dir}`.\n\n"
        "## By max stable concurrency\n\n"
        f"{table(by_conc)}\n\n"
        "## By e2e TTFA p50 at concurrency=1\n\n"
        f"{table(by_ttfa)}\n"
    )
    out = results_dir / "RESULTS.md"
    out.write_text(md, encoding="utf-8")
    return out


async def async_main(args: argparse.Namespace) -> int:
    load_dotenv(ROOT / ".env")

    stt_name = args.stt
    tts_name = args.tts
    llm_key = args.llm
    model_id = LLM_MAP[llm_key]

    placement = vram_placement(llm_key, stt_name, tts_name)
    if llm_key == "moe":
        os.environ["IFW_DEVICE"] = os.environ.get("IFW_DEVICE_MOE", "cpu")
        os.environ["MELO_DEVICE"] = os.environ.get("MELO_DEVICE_MOE", "cpu")
        os.environ["NEUTTS_BACKBONE_DEVICE"] = os.environ.get("NEUTTS_BACKBONE_DEVICE_MOE", "cpu")

    stt = build_stt(stt_name, llm_key)
    tts = build_tts(tts_name, llm_key)
    llm = VLLMLLM(
        base=os.environ.get("VLLM_BASE", "http://127.0.0.1:8000"),
        model=None,
        disable_thinking=(llm_key == "moe" or os.environ.get("DISABLE_THINKING", "1") == "1"),
    )

    fixtures = list_fixtures(
        Path(args.fixtures or os.environ.get("FIXTURES_DIR", str(ROOT / "fixtures")))
    )
    if args.fixture:
        fixtures = [Path(args.fixture)]

    print(f"combo stt={stt_name} llm={llm_key}({model_id}) tts={tts_name}", flush=True)
    print(f"placement={placement}", flush=True)

    health = {
        "stt": await stt.health(),
        "llm": await llm.health(),
        "tts": await tts.health(),
    }
    print(f"health={health}", flush=True)
    if not all(health.values()):
        print("ERROR: unhealthy stage(s)", flush=True)
        out = {
            "ok": False,
            "health": health,
            "stt": stt_name,
            "llm": llm_key,
            "llm_model": model_id,
            "tts": tts_name,
            "placement": placement,
            "gpu": gpu_snapshot(),
        }
        _write_result(args, stt_name, llm_key, tts_name, out)
        return 2

    use_stt_ws = args.stt_mode != "http" and getattr(stt, "streaming", False)
    served = await llm.resolve_model()

    print("warmup call ...", flush=True)
    warm = await run_one_call(stt, llm, tts, fixtures[0], use_stt_ws=use_stt_ws)
    print(f"warmup ok={warm.ok} e2e_ttfa_ms={warm.e2e_ttfa_ms} err={warm.error}", flush=True)

    payload: dict[str, Any] = {
        "ok": True,
        "stt": stt_name,
        "stt_streaming": getattr(stt, "streaming", False),
        "llm": llm_key,
        "llm_model_expected": model_id,
        "llm_model_served": served,
        "tts": tts_name,
        "tts_streaming": getattr(tts, "streaming", False),
        "placement": placement,
        "stop_ttfa_ms": args.stop_ttfa_ms,
        "stop_error_rate": args.stop_error_rate,
        "gpu_before": gpu_snapshot(),
        "health": health,
        "warmup": {"ok": warm.ok, "e2e_ttfa_ms": warm.e2e_ttfa_ms, "error": warm.error},
    }

    if args.find_limit:
        payload["mode"] = "find_limit"
        fl = await find_limit(
            stt,
            llm,
            tts,
            fixtures,
            start=args.sweep_start,
            max_c=args.sweep_max,
            factor=args.sweep_factor,
            stop_ttfa_ms=args.stop_ttfa_ms,
            stop_error_rate=args.stop_error_rate,
            use_stt_ws=use_stt_ws,
        )
        payload.update(fl)
        print(
            f"max_stable={fl['max_stable_concurrency']} "
            f"limit_hit_at={fl['limit_hit_at']} reason={fl['stop_reason']}",
            flush=True,
        )
    else:
        conc = 1 if args.smoke else args.concurrency
        results = await run_wave(stt, llm, tts, fixtures, conc, use_stt_ws=use_stt_ws)
        payload["mode"] = "fixed"
        payload["summary"] = summarize(results, conc)
        payload["samples"] = [r.__dict__ for r in results[: min(3, len(results))]]
        print(json.dumps(payload["summary"], indent=2), flush=True)

    payload["gpu_after"] = gpu_snapshot()
    path = _write_result(args, stt_name, llm_key, tts_name, payload)
    print(f"wrote {path}", flush=True)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Voice pipeline concurrency stress")
    p.add_argument("--stt", choices=["parakeet", "ifw"], required=False)
    p.add_argument("--llm", choices=["moe", "3b", "7b"], required=False)
    p.add_argument("--tts", choices=["kokoro", "melo", "neutts"], required=False)
    p.add_argument("--find-limit", action="store_true")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--sweep-start", type=int, default=int(os.environ.get("SWEEP_START", "1")))
    p.add_argument("--sweep-max", type=int, default=int(os.environ.get("SWEEP_MAX", "32")))
    p.add_argument("--sweep-factor", type=int, default=int(os.environ.get("SWEEP_STEP_FACTOR", "2")))
    p.add_argument("--stop-ttfa-ms", type=float, default=float(os.environ.get("STOP_TTFA_MS", "4000")))
    p.add_argument(
        "--stop-error-rate",
        type=float,
        default=float(os.environ.get("STOP_ERROR_RATE", "0.05")),
    )
    p.add_argument("--fixtures", default=None)
    p.add_argument("--fixture", default=None)
    p.add_argument("--results-dir", default=None)
    p.add_argument("--stt-mode", choices=["ws", "http"], default="ws")
    p.add_argument("--write-results-md", action="store_true")
    args = p.parse_args()

    if args.write_results_md:
        out = build_results_md(Path(args.results_dir or ROOT / "results"))
        print(out)
        return

    if not args.stt or not args.llm or not args.tts:
        p.error("--stt --llm --tts are required unless --write-results-md")

    if args.smoke:
        args.concurrency = 1
        args.find_limit = False

    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
