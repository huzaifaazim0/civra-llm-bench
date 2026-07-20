#!/usr/bin/env python3
"""
Stress-test vLLM for concurrent rephrasing.

Modes:
  single     — one concurrency level (default)
  sweep      — ramp concurrency until TTFT or TPS stop criteria
  sustained  — many waves at fixed concurrency
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import psutil

DEFAULT_BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
DEFAULT_MODEL = os.getenv("SERVED_MODEL_NAME") or os.getenv("MODEL", "Qwen2.5-3B-Instruct")
RESOURCE_SAMPLE_INTERVAL_S = float(os.getenv("RESOURCE_SAMPLE_INTERVAL_S", "0.25"))

SYSTEM_PROMPT = (
    "You are a concise rewriting assistant. "
    "Rephrase the user's text clearly while preserving meaning. "
    "Do not add commentary."
)

REPHRASE_SAMPLES = [
    "The quick brown fox jumps over the lazy dog near the riverbank.",
    "Please schedule the meeting for next Tuesday afternoon if everyone is free.",
    "Our team reduced latency by optimizing the cache and batching requests.",
    "Customer support should acknowledge the issue and offer a clear next step.",
    "The weather looks stormy, so outdoor events may need to move indoors.",
    "I need a shorter version of this email that still sounds professional.",
    "The product launch is delayed because of a supply-chain bottleneck.",
    "Can you rewrite this so it sounds more confident and less apologetic?",
    "We observed higher GPU utilization after enabling continuous batching.",
    "Summarize the risk without using jargon that non-technical readers will miss.",
    "The applicant asked whether dental and vision are included in the plan.",
    "Please make this sentence easier to understand for a first-time caller.",
    "Throughput improved once prefix caching reused the shared system prompt.",
    "Rewrite this update for a status email to leadership.",
    "The model must keep Time-To-First-Token under half a second under load.",
    "Turn this note into a polite follow-up message to the client.",
    "Explain the same idea with fewer words and no filler.",
    "The agent should confirm the caller's ZIP code before transferring.",
    "Make this sound natural for a phone conversation.",
    "Convert this technical blurb into plain English for end users.",
]

REPHRASE_SCHEMA = {
    "type": "object",
    "properties": {
        "original": {"type": "string"},
        "rephrased": {"type": "string"},
    },
    "required": ["original", "rephrased"],
}


@dataclass
class RequestResult:
    id: int
    ok: bool
    error: str | None
    ttft_ms: float | None
    total_ms: float | None
    completion_tokens: int
    tokens_per_sec: float | None
    text: str
    prompt_text: str = ""
    parsed: dict[str, Any] | None = None
    schema_ok: bool | None = None


@dataclass
class ResourceSample:
    ts: float
    cpu_percent: float
    ram_used_gb: float
    ram_total_gb: float
    ram_percent: float
    gpu_util_percent: float | None
    vram_used_mb: float | None
    vram_total_mb: float | None
    gpu_temp_c: float | None = None


def _read_nvidia() -> tuple[float | None, float | None, float | None, float | None]:
    """Return (gpu_util%, vram_used_mb, vram_total_mb, temp_c) or Nones."""
    if not shutil.which("nvidia-smi"):
        return None, None, None, None
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=2,
        ).strip().splitlines()
        if not out:
            return None, None, None, None
        # First GPU
        parts = [p.strip() for p in out[0].split(",")]
        if len(parts) < 4:
            return None, None, None, None
        return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
    except (subprocess.SubprocessError, ValueError, OSError):
        return None, None, None, None


def _series_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "avg": None, "max": None}
    return {
        "min": round(min(values), 2),
        "avg": round(statistics.mean(values), 2),
        "max": round(max(values), 2),
    }


class ResourceMonitor:
    """Background sampler for CPU / RAM / GPU / VRAM during a stress batch."""

    def __init__(self, interval_s: float = RESOURCE_SAMPLE_INTERVAL_S) -> None:
        self.interval_s = interval_s
        self.samples: list[ResourceSample] = []
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # Prime psutil cpu_percent so the first real reading is meaningful
        psutil.cpu_percent(interval=None)

    def snapshot(self) -> ResourceSample:
        vm = psutil.virtual_memory()
        gpu_util, vram_used, vram_total, temp = _read_nvidia()
        return ResourceSample(
            ts=time.time(),
            cpu_percent=float(psutil.cpu_percent(interval=None)),
            ram_used_gb=round(vm.used / (1024**3), 3),
            ram_total_gb=round(vm.total / (1024**3), 3),
            ram_percent=float(vm.percent),
            gpu_util_percent=gpu_util,
            vram_used_mb=vram_used,
            vram_total_mb=vram_total,
            gpu_temp_c=temp,
        )

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.samples.append(self.snapshot())
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
            except asyncio.TimeoutError:
                continue

    def start(self) -> None:
        self._stop.clear()
        self.samples.append(self.snapshot())
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # final sample
        try:
            self.samples.append(self.snapshot())
        except Exception:  # noqa: BLE001
            pass
        return self.summary()

    def summary(self) -> dict[str, Any]:
        if not self.samples:
            return {"samples": 0}

        cpu = [s.cpu_percent for s in self.samples]
        ram_used = [s.ram_used_gb for s in self.samples]
        ram_pct = [s.ram_percent for s in self.samples]
        gpu = [s.gpu_util_percent for s in self.samples if s.gpu_util_percent is not None]
        vram = [s.vram_used_mb for s in self.samples if s.vram_used_mb is not None]
        temp = [s.gpu_temp_c for s in self.samples if s.gpu_temp_c is not None]

        vram_total = next(
            (s.vram_total_mb for s in self.samples if s.vram_total_mb is not None),
            None,
        )
        ram_total = self.samples[-1].ram_total_gb

        return {
            "samples": len(self.samples),
            "interval_s": self.interval_s,
            "cpu_percent": _series_stats(cpu),
            "ram_used_gb": _series_stats(ram_used),
            "ram_percent": _series_stats(ram_pct),
            "ram_total_gb": ram_total,
            "gpu_util_percent": _series_stats(gpu),
            "vram_used_mb": _series_stats(vram),
            "vram_used_gb": {
                k: (round(v / 1024, 3) if v is not None else None)
                for k, v in _series_stats(vram).items()
            },
            "vram_total_mb": vram_total,
            "vram_total_gb": round(vram_total / 1024, 3) if vram_total is not None else None,
            "gpu_temp_c": _series_stats(temp),
        }


def format_resource_line(load: dict[str, Any] | None) -> str:
    if not load:
        return ""
    cpu = load.get("cpu_percent") or {}
    gpu = load.get("gpu_util_percent") or {}
    vram = load.get("vram_used_gb") or {}
    ram = load.get("ram_used_gb") or {}
    return (
        f"cpu={cpu.get('avg')}/{cpu.get('max')}%  "
        f"gpu={gpu.get('avg')}/{gpu.get('max')}%  "
        f"vram={vram.get('avg')}/{vram.get('max')}GB  "
        f"ram={ram.get('avg')}/{ram.get('max')}GB"
    )


def print_system_load(load: dict[str, Any] | None) -> None:
    if not load:
        return
    print("\nSystem load during test (avg / max):")
    cpu = load.get("cpu_percent") or {}
    gpu = load.get("gpu_util_percent") or {}
    vram_gb = load.get("vram_used_gb") or {}
    vram_mb = load.get("vram_used_mb") or {}
    ram = load.get("ram_used_gb") or {}
    ram_pct = load.get("ram_percent") or {}
    temp = load.get("gpu_temp_c") or {}
    print(
        f"  CPU %:     avg={cpu.get('avg')}  max={cpu.get('max')}  min={cpu.get('min')}"
    )
    print(
        f"  GPU %:     avg={gpu.get('avg')}  max={gpu.get('max')}  min={gpu.get('min')}"
    )
    print(
        f"  VRAM:      avg={vram_gb.get('avg')}GB ({vram_mb.get('avg')}MB)  "
        f"max={vram_gb.get('max')}GB ({vram_mb.get('max')}MB)  "
        f"total={load.get('vram_total_gb')}GB"
    )
    print(
        f"  RAM:       avg={ram.get('avg')}GB ({ram_pct.get('avg')}%)  "
        f"max={ram.get('max')}GB ({ram_pct.get('max')}%)  "
        f"total={load.get('ram_total_gb')}GB"
    )
    if temp.get("avg") is not None:
        print(
            f"  GPU temp:  avg={temp.get('avg')}C  max={temp.get('max')}C  "
            f"min={temp.get('min')}C"
        )
    print(f"  samples:   {load.get('samples')} every {load.get('interval_s')}s")


def parse_structured_text(text: str) -> tuple[dict[str, Any] | None, bool]:
    """Parse model JSON; schema_ok if original+rephrased keys exist."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # tolerate markdown fences
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None, False
        try:
            obj = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None, False
    if not isinstance(obj, dict):
        return None, False
    ok = (
        isinstance(obj.get("original"), str)
        and isinstance(obj.get("rephrased"), str)
        and bool(obj.get("rephrased"))
    )
    return obj, ok


def format_sample_output(r: RequestResult) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "id": r.id,
        "prompt": r.prompt_text,
        "text": r.text,
    }
    if r.parsed is not None or r.schema_ok is not None:
        sample["parsed"] = r.parsed
        sample["schema_ok"] = r.schema_ok
        if r.parsed and isinstance(r.parsed.get("rephrased"), str):
            sample["rephrased"] = r.parsed["rephrased"]
            sample["original"] = r.parsed.get("original")
    return sample


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = int(round((len(ordered) - 1) * p))
    return ordered[k]


def approx_token_count(text: str) -> int:
    parts = [p for p in text.replace("\n", " ").split(" ") if p]
    return max(len(parts), 1) if text.strip() else 0


def slim_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in summary.items() if k not in {"per_request", "sample_outputs", "errors"}}


async def one_request(
    client: httpx.AsyncClient,
    *,
    req_id: int,
    base_url: str,
    model: str,
    max_tokens: int,
    structured: bool,
    temperature: float,
) -> RequestResult:
    sample = REPHRASE_SAMPLES[req_id % len(REPHRASE_SAMPLES)]
    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    if structured:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a rewriting assistant. "
                    "Return ONLY a JSON object with keys "
                    '"original" and "rephrased". No markdown.'
                ),
            },
            {"role": "user", "content": f"Rephrase this:\n{sample}"},
        ]
    else:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Rephrase this:\n{sample}"},
        ]

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if structured:
        # vLLM 0.21+: use structured_outputs (guided_json is ignored)
        payload["structured_outputs"] = {"json": REPHRASE_SCHEMA}

    start = time.perf_counter()
    first_token: float | None = None
    text = ""
    completion_tokens = 0
    error: str | None = None

    try:
        async with client.stream("POST", url, json=payload, timeout=180.0) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue

                usage = obj.get("usage") or {}
                if usage.get("completion_tokens"):
                    completion_tokens = int(usage["completion_tokens"])

                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    if first_token is None:
                        first_token = time.perf_counter()
                    text += delta
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    end = time.perf_counter()
    text = text.strip()
    if completion_tokens <= 0:
        completion_tokens = approx_token_count(text)

    tokens_per_sec: float | None = None
    if first_token is not None and completion_tokens > 0:
        decode_s = max(end - first_token, 1e-6)
        tokens_per_sec = completion_tokens / decode_s

    parsed: dict[str, Any] | None = None
    schema_ok: bool | None = None
    if structured and text:
        parsed, schema_ok = parse_structured_text(text)

    ok = error is None and first_token is not None
    if structured and ok:
        ok = bool(schema_ok)

    return RequestResult(
        id=req_id,
        ok=ok,
        error=error
        if error
        else (None if ok else "structured output missing original/rephrased"),
        ttft_ms=round((first_token - start) * 1000, 2) if first_token else None,
        total_ms=round((end - start) * 1000, 2),
        completion_tokens=completion_tokens,
        tokens_per_sec=round(tokens_per_sec, 3) if tokens_per_sec is not None else None,
        text=text,
        prompt_text=sample,
        parsed=parsed,
        schema_ok=schema_ok,
    )


async def run_batch(
    *,
    concurrency: int,
    total_requests: int,
    base_url: str,
    model: str,
    max_tokens: int,
    structured: bool,
    temperature: float,
) -> dict[str, Any]:
    limits = httpx.Limits(
        max_connections=max(concurrency + 40, 64),
        max_keepalive_connections=max(concurrency + 40, 64),
    )
    sem = asyncio.Semaphore(concurrency)
    results: list[RequestResult] = []
    monitor = ResourceMonitor()

    async with httpx.AsyncClient(limits=limits) as client:

        async def wrapped(i: int) -> RequestResult:
            async with sem:
                return await one_request(
                    client,
                    req_id=i,
                    base_url=base_url,
                    model=model,
                    max_tokens=max_tokens,
                    structured=structured,
                    temperature=temperature,
                )

        monitor.start()
        wall_start = time.perf_counter()
        try:
            tasks = [asyncio.create_task(wrapped(i)) for i in range(total_requests)]
            for task in asyncio.as_completed(tasks):
                results.append(await task)
        finally:
            wall_end = time.perf_counter()
            system_load = await monitor.stop()

    ok = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    ttfts = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    tps_values = [r.tokens_per_sec for r in ok if r.tokens_per_sec is not None]
    duration = wall_end - wall_start
    total_completion_tokens = sum(r.completion_tokens for r in ok)
    schema_ok_count = sum(1 for r in results if r.schema_ok)

    return {
        "base_url": base_url,
        "model": model,
        "structured": structured,
        "concurrency": concurrency,
        "total_requests": total_requests,
        "duration_sec": round(duration, 2),
        "ok": len(ok),
        "failed": len(failed),
        "error_rate_percent": round((len(failed) / max(len(results), 1)) * 100, 2),
        "schema_ok_count": schema_ok_count if structured else None,
        "aggregate_tokens_per_sec": round(total_completion_tokens / max(duration, 1e-6), 2),
        "ttft_avg_ms": round(statistics.mean(ttfts), 2) if ttfts else None,
        "ttft_p50_ms": percentile(ttfts, 0.50),
        "ttft_p95_ms": percentile(ttfts, 0.95),
        "ttft_p99_ms": percentile(ttfts, 0.99),
        "ttft_max_ms": max(ttfts) if ttfts else None,
        "tps_avg": round(statistics.mean(tps_values), 3) if tps_values else None,
        "tps_p50": percentile(tps_values, 0.50),
        "tps_p95": percentile(tps_values, 0.95),
        "tps_min": min(tps_values) if tps_values else None,
        "system_load": system_load,
        "sample_outputs": [format_sample_output(r) for r in ok[:5]],
        "errors": [r.error for r in failed[:5] if r.error],
        "per_request": [asdict(r) for r in results],
    }


def evaluate(
    summary: dict[str, Any],
    *,
    ttft_budget_ms: float,
    min_tps: float,
) -> dict[str, Any]:
    ttft_p95 = summary.get("ttft_p95_ms")
    tps_min = summary.get("tps_min")
    tps_avg = summary.get("tps_avg")
    checks = {
        "all_ok": summary["failed"] == 0,
        "ttft_p95_under_budget": ttft_p95 is not None and ttft_p95 < ttft_budget_ms,
        "min_tps_met": tps_min is not None and tps_min >= min_tps,
        "avg_tps_met": tps_avg is not None and tps_avg >= min_tps,
    }
    return {
        "ttft_budget_ms": ttft_budget_ms,
        "min_tps": min_tps,
        "checks": checks,
        "passed": all(checks.values()),
    }


def stop_reason(
    summary: dict[str, Any],
    *,
    stop_ttft_ms: float,
    stop_min_tps: float,
) -> str | None:
    """Return why we should stop the sweep, or None to continue."""
    if summary["failed"] > 0 and summary["error_rate_percent"] >= 50:
        return f"error_rate={summary['error_rate_percent']}%"
    ttft_p95 = summary.get("ttft_p95_ms")
    if ttft_p95 is not None and ttft_p95 > stop_ttft_ms:
        return f"ttft_p95={ttft_p95}ms > {stop_ttft_ms}ms"
    tps_min = summary.get("tps_min")
    if tps_min is not None and tps_min < stop_min_tps:
        return f"tps_min={tps_min} < {stop_min_tps}"
    if summary.get("ok", 0) == 0:
        return "zero_successful_requests"
    return None


def print_level_line(summary: dict[str, Any]) -> None:
    c = summary["concurrency"]
    ttft = summary.get("ttft_p95_ms")
    tps_min = summary.get("tps_min")
    tps_avg = summary.get("tps_avg")
    agg = summary.get("aggregate_tokens_per_sec")
    err = summary.get("error_rate_percent")
    load = format_resource_line(summary.get("system_load"))
    print(
        f"c={c:>4}  ttft_p95={ttft!s:>8}ms  "
        f"tps_min={tps_min!s:>8}  tps_avg={tps_avg!s:>8}  "
        f"agg_tps={agg!s:>8}  err%={err}"
    )
    if load:
        print(f"       {load}")


def print_report(summary: dict[str, Any], verdict: dict[str, Any]) -> None:
    print(json.dumps({"summary": slim_summary(summary), "verdict": verdict}, indent=2))
    print_system_load(summary.get("system_load"))
    if summary.get("sample_outputs"):
        print("\nSample outputs:")
        for i, sample in enumerate(summary["sample_outputs"], 1):
            if isinstance(sample, dict):
                print(f"\n  [{i}] prompt: {sample.get('prompt')}")
                print(f"      text:   {sample.get('text')}")
                if sample.get("parsed") is not None:
                    print(f"      schema_ok: {sample.get('schema_ok')}")
                    print("      parsed:")
                    for line in json.dumps(sample["parsed"], indent=2).splitlines():
                        print(f"        {line}")
                elif sample.get("rephrased"):
                    print(f"      rephrased: {sample.get('rephrased')}")
            else:
                print(f"  [{i}] {sample}")
    if summary.get("errors"):
        print("\nSample errors:")
        for err in summary["errors"]:
            print(f"  - {err}")
    status = "PASS" if verdict["passed"] else "FAIL"
    print(f"\n=== {status} ===")
    for name, ok in verdict["checks"].items():
        print(f"  [{'OK' if ok else 'NO'}] {name}")


async def run_single(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    total = args.requests if args.requests > 0 else args.concurrency
    summary = await run_batch(
        concurrency=args.concurrency,
        total_requests=total,
        base_url=args.base_url,
        model=args.model,
        max_tokens=args.max_tokens,
        structured=args.structured,
        temperature=args.temperature,
    )
    verdict = evaluate(summary, ttft_budget_ms=args.ttft_ms, min_tps=args.min_tps)
    print_report(summary, verdict)
    out = {
        "mode": "single",
        "summary": slim_summary(summary) | {
            "sample_outputs": summary.get("sample_outputs"),
            "errors": summary.get("errors"),
        },
        "verdict": verdict,
        "per_request": summary["per_request"],
    }
    Path(args.output).write_text(json.dumps(out, indent=2))
    print(f"\nWrote {args.output}")
    return out, (0 if verdict["passed"] else 1)


async def run_sweep(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    levels: list[dict[str, Any]] = []
    limit_hit_at: int | None = None
    reason: str | None = None

    print(
        f"Sweep concurrency {args.sweep_start}..{args.sweep_max} "
        f"step={args.sweep_step}  stop: TTFT p95>{args.stop_ttft_ms}ms "
        f"OR tps_min<{args.stop_min_tps}"
    )
    print("-" * 88)

    conc = args.sweep_start
    while conc <= args.sweep_max:
        total = max(conc * args.sweep_waves, conc)
        print(f"\n>>> concurrency={conc} requests={total}")
        summary = await run_batch(
            concurrency=conc,
            total_requests=total,
            base_url=args.base_url,
            model=args.model,
            max_tokens=args.max_tokens,
            structured=args.structured,
            temperature=args.temperature,
        )
        row = slim_summary(summary)
        levels.append(row)
        print_level_line(summary)

        reason = stop_reason(
            summary,
            stop_ttft_ms=args.stop_ttft_ms,
            stop_min_tps=args.stop_min_tps,
        )
        if reason:
            limit_hit_at = conc
            print(f"\nSTOP at concurrency={conc}: {reason}")
            break

        if conc == args.sweep_max:
            break
        next_c = conc + args.sweep_step
        if next_c > args.sweep_max and conc < args.sweep_max:
            conc = args.sweep_max
        else:
            conc = next_c

    max_ok = None
    for row in levels:
        r = stop_reason(row, stop_ttft_ms=args.stop_ttft_ms, stop_min_tps=args.stop_min_tps)
        if r is None:
            max_ok = row["concurrency"]
        else:
            break

    out = {
        "mode": "sweep",
        "stop_criteria": {
            "stop_ttft_ms": args.stop_ttft_ms,
            "stop_min_tps": args.stop_min_tps,
        },
        "limit_hit_at": limit_hit_at,
        "stop_reason": reason,
        "max_stable_concurrency": max_ok,
        "levels": levels,
    }
    Path(args.output).write_text(json.dumps(out, indent=2))
    print("\n" + "=" * 88)
    print(f"max_stable_concurrency: {max_ok}")
    print(f"limit_hit_at: {limit_hit_at} ({reason})")
    print(f"Wrote {args.output}")
    return out, 0


async def run_sustained(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    waves: list[dict[str, Any]] = []
    conc = args.concurrency
    print(f"Sustained: concurrency={conc} waves={args.waves}")
    print("-" * 88)

    for w in range(1, args.waves + 1):
        print(f"\n>>> wave {w}/{args.waves}")
        summary = await run_batch(
            concurrency=conc,
            total_requests=conc,
            base_url=args.base_url,
            model=args.model,
            max_tokens=args.max_tokens,
            structured=args.structured,
            temperature=args.temperature,
        )
        row = slim_summary(summary)
        row["wave"] = w
        waves.append(row)
        print_level_line(summary)

        reason = stop_reason(
            summary,
            stop_ttft_ms=args.stop_ttft_ms,
            stop_min_tps=args.stop_min_tps,
        )
        if reason:
            print(f"\nSTOP at wave={w}: {reason}")
            break

    ttfts = [w["ttft_p95_ms"] for w in waves if w.get("ttft_p95_ms") is not None]
    tps_mins = [w["tps_min"] for w in waves if w.get("tps_min") is not None]
    out = {
        "mode": "sustained",
        "concurrency": conc,
        "waves_completed": len(waves),
        "ttft_p95_trend_ms": ttfts,
        "tps_min_trend": tps_mins,
        "waves": waves,
    }
    Path(args.output).write_text(json.dumps(out, indent=2))
    print(f"\nWrote {args.output}")
    return out, 0


async def async_main(args: argparse.Namespace) -> int:
    if args.mode == "sweep":
        _, code = await run_sweep(args)
    elif args.mode == "sustained":
        _, code = await run_sustained(args)
    else:
        _, code = await run_single(args)
    return code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="vLLM concurrent rephrasing stress test")
    p.add_argument("--mode", choices=["single", "sweep", "sustained"], default="single")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--concurrency", type=int, default=int(os.getenv("CONCURRENCY", "20")))
    p.add_argument("--requests", type=int, default=int(os.getenv("REQUESTS", "0")))
    p.add_argument("--max-tokens", type=int, default=int(os.getenv("MAX_TOKENS", "64")))
    p.add_argument("--temperature", type=float, default=float(os.getenv("TEMPERATURE", "0.2")))
    p.add_argument("--ttft-ms", type=float, default=float(os.getenv("TTFT_MS", "500")))
    p.add_argument("--min-tps", type=float, default=float(os.getenv("MIN_TPS", "4")))
    p.add_argument("--structured", action="store_true")
    p.add_argument("--output", default="stress_results.json")

    # Sweep / stop criteria
    p.add_argument("--sweep-start", type=int, default=int(os.getenv("SWEEP_START", "1")))
    p.add_argument("--sweep-max", type=int, default=int(os.getenv("SWEEP_MAX", "200")))
    p.add_argument("--sweep-step", type=int, default=int(os.getenv("SWEEP_STEP", "5")))
    p.add_argument("--sweep-waves", type=int, default=int(os.getenv("SWEEP_WAVES", "1")))
    p.add_argument("--stop-ttft-ms", type=float, default=float(os.getenv("STOP_TTFT_MS", "1500")))
    p.add_argument("--stop-min-tps", type=float, default=float(os.getenv("STOP_MIN_TPS", "4")))
    p.add_argument("--waves", type=int, default=int(os.getenv("SUSTAINED_WAVES", "10")))
    return p


def main() -> None:
    args = build_parser().parse_args()
    if args.requests <= 0:
        args.requests = args.concurrency
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
