#!/usr/bin/env python3
"""Medicare fronter multi-turn correctness + concurrency stress harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from flows import SCENARIOS, session_scripts_for_stress, stress_turn_contexts
from prompts import (
    build_system_prompt,
    build_turn_user_content,
    resolve_prompt_style,
    trim_messages,
)
from report import (
    model_slug,
    summarize_turn_metrics,
    write_correctness_markdown,
    write_json,
    write_stress_markdown,
)
from schema import FRONTER_SCHEMA
from validators import score_turn

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def approx_token_count(text: str) -> int:
    parts = [p for p in text.replace("\n", " ").split(" ") if p]
    return max(len(parts), 1) if text.strip() else 0


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = int(round((len(ordered) - 1) * p))
    return ordered[k]


async def detect_model(client: httpx.AsyncClient, base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/v1/models"
    resp = await client.get(url, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    models = data.get("data") or []
    if not models:
        raise RuntimeError("No models returned from /v1/models")
    return models[0]["id"]


def apply_structured_payload(
    payload: dict[str, Any],
    *,
    structured_mode: str,
) -> None:
    if structured_mode == "vllm":
        payload["structured_outputs"] = {"json": FRONTER_SCHEMA}
    elif structured_mode == "openai":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "medicare_fronter",
                "schema": FRONTER_SCHEMA,
            },
        }
    # prompt mode: schema already in system prompt


@dataclass
class TurnResult:
    ok: bool
    schema_ok: bool
    error: str | None
    ttft_ms: float | None
    total_ms: float | None
    completion_tokens: int
    tokens_per_sec: float | None
    text: str
    parsed: dict[str, Any] | None = None
    score: dict[str, Any] = field(default_factory=dict)
    scenario_id: str | None = None
    turn_index: int = 0


async def stream_chat(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    structured_mode: str,
) -> TurnResult:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    apply_structured_payload(payload, structured_mode=structured_mode)

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

    return TurnResult(
        ok=error is None and first_token is not None,
        schema_ok=False,
        error=error,
        ttft_ms=round((first_token - start) * 1000, 2) if first_token else None,
        total_ms=round((end - start) * 1000, 2),
        completion_tokens=completion_tokens,
        tokens_per_sec=round(tokens_per_sec, 3) if tokens_per_sec is not None else None,
        text=text,
    )


def turn_to_dict(tr: TurnResult) -> dict[str, Any]:
    d: dict[str, Any] = {
        "scenario_id": tr.scenario_id,
        "turn_index": tr.turn_index,
        "ok": tr.ok,
        "schema_ok": tr.schema_ok,
        "error": tr.error,
        "ttft_ms": tr.ttft_ms,
        "total_ms": tr.total_ms,
        "completion_tokens": tr.completion_tokens,
        "tokens_per_sec": tr.tokens_per_sec,
        "text": tr.text,
        "parsed": tr.parsed,
    }
    if tr.score:
        d.update(
            {
                "action_ok": tr.score.get("action_ok"),
                "next_ok": tr.score.get("next_ok"),
                "state_ok": tr.score.get("state_ok"),
                "message_ok": tr.score.get("message_ok"),
                "flags_ok": tr.score.get("flags_ok"),
                "state_machine_ok": tr.score.get("state_machine_ok"),
                "expect_errors": tr.score.get("expect_errors"),
                "schema_errors": tr.score.get("schema_errors"),
                "state_machine_errors": tr.score.get("state_machine_errors"),
            }
        )
    return d


async def run_scenario(
    client: httpx.AsyncClient,
    scenario: dict[str, Any],
    *,
    base_url: str,
    model: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    structured_mode: str,
    context_turns: int,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    prior_state: dict[str, Any] | None = None
    turn_results: list[dict[str, Any]] = []

    for idx, turn in enumerate(scenario["turns"]):
        user_text = turn.get("user") or ""
        is_opening = idx == 0 and not user_text.strip()
        user_content = build_turn_user_content(
            user_text=user_text,
            prior_state=prior_state,
            is_opening=is_opening,
        )
        messages.append({"role": "user", "content": user_content})
        messages = trim_messages(messages, context_turns=context_turns)

        tr = await stream_chat(
            client,
            base_url=base_url,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            structured_mode=structured_mode,
        )
        tr.scenario_id = scenario["id"]
        tr.turn_index = idx

        if tr.error:
            tr.ok = False
            turn_results.append(turn_to_dict(tr))
            break

        score = score_turn(tr.text, turn.get("expect"))
        tr.score = score
        tr.schema_ok = bool(score.get("schema_ok"))
        tr.parsed = score.get("parsed")
        tr.ok = bool(score.get("ok")) and tr.error is None

        # Feed assistant JSON back for multi-turn continuity
        messages.append({"role": "assistant", "content": tr.text})
        if tr.parsed and isinstance(tr.parsed.get("state"), dict):
            prior_state = tr.parsed["state"]

        turn_results.append(turn_to_dict(tr))

        # Stop scenario early on hard failure for cleaner sessions (still recorded)
        if not tr.ok and turn.get("expect"):
            # continue collecting? Plan says verify each step — keep going for correctness
            pass

    return {
        "id": scenario["id"],
        "description": scenario.get("description"),
        "turns": turn_results,
        "passed": all(t.get("ok") for t in turn_results) and bool(turn_results),
    }


def build_error_taxonomy(scenarios: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in scenarios:
        for t in s.get("turns") or []:
            if t.get("ok"):
                continue
            if not t.get("schema_ok"):
                counts["schema"] = counts.get("schema", 0) + 1
            if t.get("state_machine_ok") is False:
                counts["state_machine"] = counts.get("state_machine", 0) + 1
            if t.get("action_ok") is False:
                counts["action"] = counts.get("action", 0) + 1
            if t.get("next_ok") is False:
                counts["next"] = counts.get("next", 0) + 1
            if t.get("state_ok") is False:
                counts["state_fields"] = counts.get("state_fields", 0) + 1
            if t.get("flags_ok") is False:
                counts["flags"] = counts.get("flags", 0) + 1
            if t.get("message_ok") is False:
                counts["message_soft"] = counts.get("message_soft", 0) + 1
            if t.get("error"):
                counts["http_or_stream"] = counts.get("http_or_stream", 0) + 1
    return counts


async def mode_correctness(args: argparse.Namespace) -> dict[str, Any]:
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    async with httpx.AsyncClient(limits=limits) as client:
        model = args.model or await detect_model(client, args.base_url)
        prompt_style = resolve_prompt_style(args.prompt_style, model)
        system_prompt = build_system_prompt(
            agent_name=args.agent_name,
            department=args.department,
            style=prompt_style,
            model=model,
        )
        print(f"Model: {model}")
        print(f"Prompt style: {prompt_style}")
        print(f"Running {len(SCENARIOS)} correctness scenarios…")
        scenarios_out: list[dict[str, Any]] = []
        for scenario in SCENARIOS:
            print(f"  → {scenario['id']}")
            result = await run_scenario(
                client,
                scenario,
                base_url=args.base_url,
                model=model,
                system_prompt=system_prompt,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                structured_mode=args.structured_mode,
                context_turns=args.context_turns,
            )
            status = "PASS" if result["passed"] else "FAIL"
            print(f"    {status} ({len(result['turns'])} turns)")
            scenarios_out.append(result)

    all_turns = [t for s in scenarios_out for t in s["turns"]]
    metrics = summarize_turn_metrics(all_turns)
    taxonomy = build_error_taxonomy(scenarios_out)
    payload = {
        "mode": "correctness",
        "model": model,
        "base_url": args.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_name": args.agent_name,
        "prompt_style": prompt_style,
        "structured_mode": args.structured_mode,
        "scenarios": scenarios_out,
        "metrics": metrics,
        "error_taxonomy": taxonomy,
        "passed_scenarios": sum(1 for s in scenarios_out if s["passed"]),
        "total_scenarios": len(scenarios_out),
    }
    slug = model_slug(model)
    json_path = RESULTS / f"fronter_correctness_{slug}.json"
    md_path = RESULTS / f"fronter_correctness_{slug}.md"
    write_json(json_path, payload)
    write_correctness_markdown(md_path, payload)
    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")
    print(
        f"Scenarios passed: {payload['passed_scenarios']}/{payload['total_scenarios']}  "
        f"turn ok_rate={metrics.get('ok_rate')}  error_rate={metrics.get('error_rate')}"
    )
    return payload


async def one_stress_turn(
    client: httpx.AsyncClient,
    ctx: dict[str, Any],
    *,
    req_id: int,
    base_url: str,
    model: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    structured_mode: str,
) -> TurnResult:
    user_content = build_turn_user_content(
        user_text=ctx.get("user") or "",
        prior_state=ctx.get("prior_state"),
        is_opening=bool(ctx.get("is_opening")),
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    tr = await stream_chat(
        client,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        structured_mode=structured_mode,
    )
    tr.scenario_id = ctx.get("id")
    tr.turn_index = req_id
    if tr.error:
        tr.ok = False
        return tr
    score = score_turn(tr.text, expect=None)
    tr.score = score
    tr.schema_ok = bool(score.get("schema_ok"))
    tr.parsed = score.get("parsed")
    # For stress turns without expect: ok = schema + state machine
    tr.ok = bool(score.get("schema_ok")) and bool(score.get("state_machine_ok"))
    return tr


async def mode_stress_turns(args: argparse.Namespace) -> dict[str, Any]:
    contexts = stress_turn_contexts()
    concurrency = args.concurrency
    total = args.requests
    limits = httpx.Limits(
        max_connections=max(concurrency + 40, 64),
        max_keepalive_connections=max(concurrency + 40, 64),
    )
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(limits=limits) as client:
        model = args.model or await detect_model(client, args.base_url)
        prompt_style = resolve_prompt_style(args.prompt_style, model)
        system_prompt = build_system_prompt(
            agent_name=args.agent_name,
            department=args.department,
            style=prompt_style,
            model=model,
        )
        print(
            f"Model: {model}  prompt={prompt_style}  "
            f"concurrency={concurrency}  requests={total}"
        )

        async def wrapped(i: int) -> TurnResult:
            ctx = contexts[i % len(contexts)]
            async with sem:
                return await one_stress_turn(
                    client,
                    ctx,
                    req_id=i,
                    base_url=args.base_url,
                    model=model,
                    system_prompt=system_prompt,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    structured_mode=args.structured_mode,
                )

        wall_start = time.perf_counter()
        results = await asyncio.gather(*[wrapped(i) for i in range(total)])
        wall_s = time.perf_counter() - wall_start

    turns = [turn_to_dict(r) for r in results]
    metrics = summarize_turn_metrics(turns)
    payload = {
        "mode": "stress_turns",
        "model": model,
        "prompt_style": prompt_style,
        "base_url": args.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": concurrency,
        "requests": total,
        "wall_s": round(wall_s, 3),
        "structured_mode": args.structured_mode,
        "metrics": metrics,
        "per_request": turns,
    }
    slug = model_slug(model)
    json_path = RESULTS / f"fronter_stress_turns_{slug}_{concurrency}c.json"
    md_path = RESULTS / f"fronter_stress_turns_{slug}_{concurrency}c.md"
    write_json(json_path, payload)
    write_stress_markdown(md_path, payload)
    print(f"Wrote {json_path}")
    _print_metrics(metrics)
    return payload


async def run_session_worker(
    client: httpx.AsyncClient,
    scenario: dict[str, Any],
    *,
    worker_id: int,
    base_url: str,
    model: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    structured_mode: str,
    context_turns: int,
) -> dict[str, Any]:
    session_start = time.perf_counter()
    result = await run_scenario(
        client,
        scenario,
        base_url=base_url,
        model=model,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        structured_mode=structured_mode,
        context_turns=context_turns,
    )
    result["worker_id"] = worker_id
    result["session_total_ms"] = round((time.perf_counter() - session_start) * 1000, 2)
    return result


async def mode_stress_sessions(
    args: argparse.Namespace,
    *,
    concurrency: int | None = None,
    sessions: int | None = None,
) -> dict[str, Any]:
    scripts = session_scripts_for_stress()
    concurrency = concurrency if concurrency is not None else args.concurrency
    sessions = sessions if sessions is not None else args.sessions
    limits = httpx.Limits(
        max_connections=max(concurrency + 40, 64),
        max_keepalive_connections=max(concurrency + 40, 64),
    )
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(limits=limits) as client:
        model = args.model or await detect_model(client, args.base_url)
        prompt_style = resolve_prompt_style(args.prompt_style, model)
        system_prompt = build_system_prompt(
            agent_name=args.agent_name,
            department=args.department,
            style=prompt_style,
            model=model,
        )

        async def wrapped(i: int) -> dict[str, Any]:
            scenario = scripts[i % len(scripts)]
            async with sem:
                return await run_session_worker(
                    client,
                    scenario,
                    worker_id=i,
                    base_url=args.base_url,
                    model=model,
                    system_prompt=system_prompt,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    structured_mode=args.structured_mode,
                    context_turns=args.context_turns,
                )

        print(
            f"Model: {model}  prompt={prompt_style}  concurrent sessions={concurrency}  "
            f"total sessions={sessions}"
        )
        wall_start = time.perf_counter()
        session_results = await asyncio.gather(*[wrapped(i) for i in range(sessions)])
        wall_s = time.perf_counter() - wall_start

    all_turns = [t for s in session_results for t in s.get("turns") or []]
    metrics = summarize_turn_metrics(all_turns)
    session_ok = sum(1 for s in session_results if s.get("passed"))
    payload = {
        "mode": "stress_sessions",
        "model": model,
        "prompt_style": prompt_style,
        "base_url": args.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": concurrency,
        "sessions": sessions,
        "wall_s": round(wall_s, 3),
        "structured_mode": args.structured_mode,
        "session_pass_rate": round(session_ok / sessions, 4) if sessions else None,
        "metrics": metrics,
        "sessions_detail": [
            {
                "worker_id": s.get("worker_id"),
                "id": s.get("id"),
                "passed": s.get("passed"),
                "session_total_ms": s.get("session_total_ms"),
                "turn_count": len(s.get("turns") or []),
            }
            for s in session_results
        ],
        "per_turn": all_turns,
    }
    return payload


async def mode_stress_sessions_and_write(args: argparse.Namespace) -> dict[str, Any]:
    payload = await mode_stress_sessions(args)
    model = payload["model"]
    concurrency = payload["concurrency"]
    slug = model_slug(model)
    json_path = RESULTS / f"fronter_stress_sessions_{slug}_{concurrency}c.json"
    md_path = RESULTS / f"fronter_stress_sessions_{slug}_{concurrency}c.md"
    write_json(json_path, payload)
    write_stress_markdown(md_path, payload)
    print(f"Wrote {json_path}")
    _print_metrics(payload["metrics"])
    print(f"Session pass rate: {payload.get('session_pass_rate')}")
    return payload


def should_stop(
    metrics: dict[str, Any],
    *,
    stop_ttft_ms: float,
    stop_min_tps: float,
    max_error_rate: float,
) -> str | None:
    ttft_p95 = metrics.get("ttft_p95_ms")
    tps_min = metrics.get("tps_min")
    error_rate = metrics.get("error_rate")
    if ttft_p95 is not None and ttft_p95 > stop_ttft_ms:
        return f"ttft_p95={ttft_p95}ms > {stop_ttft_ms}ms"
    if tps_min is not None and tps_min < stop_min_tps:
        return f"tps_min={tps_min} < {stop_min_tps}"
    if error_rate is not None and error_rate > max_error_rate:
        return f"error_rate={error_rate} > {max_error_rate}"
    return None


async def mode_find_limit(args: argparse.Namespace) -> dict[str, Any]:
    sweep: list[dict[str, Any]] = []
    max_stable = 0
    stop_reason: str | None = None
    model: str | None = None

    c = args.sweep_start
    while c <= args.sweep_max:
        print(f"\n=== sweep concurrency={c} ===")
        # sessions == concurrency for each wave (one full wave)
        for wave in range(args.sweep_waves):
            args_ns = argparse.Namespace(**vars(args))
            payload = await mode_stress_sessions(
                args_ns, concurrency=c, sessions=c
            )
            model = payload["model"]
            metrics = payload["metrics"]
            reason = should_stop(
                metrics,
                stop_ttft_ms=args.stop_ttft_ms,
                stop_min_tps=args.stop_min_tps,
                max_error_rate=args.max_error_rate,
            )
            row = {
                "concurrency": c,
                "wave": wave,
                "ttft_p95_ms": metrics.get("ttft_p95_ms"),
                "tps_min": metrics.get("tps_min"),
                "error_rate": metrics.get("error_rate"),
                "ok_rate": metrics.get("ok_rate"),
                "session_pass_rate": payload.get("session_pass_rate"),
                "stopped": reason is not None,
                "stop_reason": reason,
            }
            sweep.append(row)
            print(
                f"  c={c} wave={wave} ttft_p95={row['ttft_p95_ms']} "
                f"tps_min={row['tps_min']} err={row['error_rate']} "
                f"{'STOP: ' + reason if reason else 'ok'}"
            )
            if reason:
                stop_reason = reason
                break
            max_stable = c
        if stop_reason:
            break
        c += args.sweep_step

    payload = {
        "mode": "find_limit",
        "model": model or args.model or "unknown",
        "base_url": args.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": max_stable,
        "max_stable_concurrency": max_stable,
        "stop_reason": stop_reason or "reached sweep_max",
        "sweep": sweep,
        "metrics": sweep[-1] if sweep else {},
        "structured_mode": args.structured_mode,
        "stop_ttft_ms": args.stop_ttft_ms,
        "stop_min_tps": args.stop_min_tps,
        "max_error_rate": args.max_error_rate,
    }
    # Flatten last metrics for markdown helper
    if sweep:
        last = sweep[-2] if stop_reason and len(sweep) > 1 else sweep[-1]
        payload["metrics"] = {
            "turns": None,
            "ok_rate": last.get("ok_rate"),
            "error_rate": last.get("error_rate"),
            "schema_ok_rate": None,
            "ttft_p50_ms": None,
            "ttft_p95_ms": last.get("ttft_p95_ms"),
            "ttft_max_ms": None,
            "total_p50_ms": None,
            "total_p95_ms": None,
            "total_max_ms": None,
            "tps_avg": None,
            "tps_min": last.get("tps_min"),
        }

    slug = model_slug(payload["model"])
    json_path = RESULTS / f"fronter_find_limit_{slug}.json"
    md_path = RESULTS / f"fronter_find_limit_{slug}.md"
    write_json(json_path, payload)
    write_stress_markdown(md_path, payload)
    print(f"\nWrote {json_path}")
    print(f"max_stable_concurrency={max_stable}  stop={payload['stop_reason']}")
    return payload


def _print_metrics(metrics: dict[str, Any]) -> None:
    print(
        f"  turns={metrics.get('turns')}  ok_rate={metrics.get('ok_rate')}  "
        f"error_rate={metrics.get('error_rate')}"
    )
    print(
        f"  TTFT p50/p95/max: {metrics.get('ttft_p50_ms')}/"
        f"{metrics.get('ttft_p95_ms')}/{metrics.get('ttft_max_ms')} ms"
    )
    print(
        f"  Full gen p50/p95/max: {metrics.get('total_p50_ms')}/"
        f"{metrics.get('total_p95_ms')}/{metrics.get('total_max_ms')} ms"
    )
    print(
        f"  TPS avg/min: {metrics.get('tps_avg')}/{metrics.get('tps_min')}"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Medicare fronter LLM stress/correctness")
    p.add_argument(
        "mode",
        choices=["correctness", "stress_turns", "stress_sessions", "find_limit"],
    )
    p.add_argument("--base-url", default=os.getenv("BASE_URL", "http://127.0.0.1:8000"))
    p.add_argument("--model", default=os.getenv("MODEL") or None)
    p.add_argument("--agent-name", default=os.getenv("AGENT_NAME", "Sarah"))
    p.add_argument(
        "--department", default=os.getenv("DEPARTMENT", "Medicare department")
    )
    p.add_argument(
        "--structured-mode",
        default=os.getenv("STRUCTURED_MODE", "vllm"),
        choices=["vllm", "openai", "prompt"],
    )
    p.add_argument(
        "--prompt-style",
        default=os.getenv("PROMPT_STYLE", "auto"),
        choices=["auto", "full", "compact"],
        help="auto=compact for small models (3B/4B/E4B), full for larger",
    )
    p.add_argument("--max-tokens", type=int, default=int(os.getenv("MAX_TOKENS", "256")))
    p.add_argument(
        "--temperature", type=float, default=float(os.getenv("TEMPERATURE", "0.1"))
    )
    p.add_argument(
        "--context-turns", type=int, default=int(os.getenv("CONTEXT_TURNS", "3"))
    )
    p.add_argument(
        "--concurrency", type=int, default=int(os.getenv("CONCURRENCY", "10"))
    )
    p.add_argument("--requests", type=int, default=int(os.getenv("REQUESTS", "20")))
    p.add_argument("--sessions", type=int, default=int(os.getenv("SESSIONS", "10")))
    p.add_argument(
        "--sweep-start", type=int, default=int(os.getenv("SWEEP_START", "1"))
    )
    p.add_argument("--sweep-max", type=int, default=int(os.getenv("SWEEP_MAX", "100")))
    p.add_argument("--sweep-step", type=int, default=int(os.getenv("SWEEP_STEP", "5")))
    p.add_argument(
        "--sweep-waves", type=int, default=int(os.getenv("SWEEP_WAVES", "1"))
    )
    p.add_argument(
        "--stop-ttft-ms",
        type=float,
        default=float(os.getenv("STOP_TTFT_MS", "1500")),
    )
    p.add_argument(
        "--stop-min-tps",
        type=float,
        default=float(os.getenv("STOP_MIN_TPS", "4")),
    )
    p.add_argument(
        "--max-error-rate",
        type=float,
        default=float(os.getenv("MAX_ERROR_RATE", "0.05")),
    )
    return p


async def async_main(args: argparse.Namespace) -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.mode == "correctness":
        await mode_correctness(args)
    elif args.mode == "stress_turns":
        await mode_stress_turns(args)
    elif args.mode == "stress_sessions":
        await mode_stress_sessions_and_write(args)
    elif args.mode == "find_limit":
        await mode_find_limit(args)
    else:
        print(f"Unknown mode: {args.mode}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
