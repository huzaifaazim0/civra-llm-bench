#!/usr/bin/env python3
"""Medicare closer multi-turn correctness, freeform export, interactive, and stress."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from flows import SCENARIOS, session_scripts_for_stress, stress_turn_contexts
from plans import DEFAULT_EFFECTIVE_DATE
from prompts import (
    build_system_prompt,
    build_turn_user_content,
    extract_spoken_message,
    resolve_prompt_style,
    trim_messages,
)
from controller import CloserController, assemble_response
from understand import (
    UNDERSTAND_SYSTEM,
    Understanding,
    build_understand_user,
    offline_understanding,
    parse_understanding,
)
from voice import build_voice_system_prompt, build_voice_turn_user
from report import (
    model_slug,
    summarize_turn_metrics,
    write_correctness_markdown,
    write_freeform_transcript,
    write_json,
    write_stress_markdown,
)
from schema import CLOSER_SCHEMA
from validators import score_turn

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
JUDGE_DIR = ROOT / "judge"
USE_CONTROLLER = os.getenv("USE_CONTROLLER", "1").strip() not in ("0", "false", "False", "no")
# Extra LLM judge before speech delays TTFT of the spoken reply. Keep 0 for interactive.
USE_LLM_UNDERSTAND = os.getenv("USE_LLM_UNDERSTAND", "0").strip() not in (
    "0",
    "false",
    "False",
    "no",
)
# SLO: time-to-first-token of the spoken LLM reply (not total generation time).
INTERACTIVE_TARGET_TTFT_MS = float(
    os.getenv("INTERACTIVE_TARGET_TTFT_MS", os.getenv("INTERACTIVE_TARGET_MS", "555"))
)
INTERACTIVE_MAX_TOKENS = int(os.getenv("INTERACTIVE_MAX_TOKENS", "120"))
INTERACTIVE_CONTEXT_TURNS = int(os.getenv("INTERACTIVE_CONTEXT_TURNS", "6"))



def approx_token_count(text: str) -> int:
    parts = [p for p in text.replace("\n", " ").split(" ") if p]
    return max(len(parts), 1) if text.strip() else 0


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
    freeform: bool,
) -> None:
    if freeform:
        return
    if structured_mode == "vllm":
        payload["structured_outputs"] = {"json": CLOSER_SCHEMA}
    elif structured_mode == "openai":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "medicare_closer",
                "schema": CLOSER_SCHEMA,
            },
        }


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
    freeform: bool = False,
    on_delta: Any | None = None,
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
    apply_structured_payload(
        payload, structured_mode=structured_mode, freeform=freeform
    )

    start = time.perf_counter()
    first_token: float | None = None
    text = ""
    completion_tokens = 0
    error: str | None = None

    async def _consume(stream_payload: dict[str, Any]) -> tuple[str, float | None, int, str | None]:
        local_text = ""
        local_first: float | None = None
        local_tokens = 0
        local_err: str | None = None
        try:
            async with client.stream(
                "POST", url, json=stream_payload, timeout=300.0
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    return "", None, 0, f"HTTP {response.status_code}: {body[:800]}"
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
                        local_tokens = int(usage["completion_tokens"])
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0].get("delta") or {}).get("content") or ""
                    if delta:
                        if local_first is None:
                            local_first = time.perf_counter()
                        local_text += delta
                        if on_delta is not None:
                            on_delta(delta)
        except Exception as exc:  # noqa: BLE001
            local_err = str(exc)
        return local_text, local_first, local_tokens, local_err

    text, first_token, completion_tokens, error = await _consume(payload)

    # Retry once without guided JSON if structured request was rejected
    if (
        error
        and not freeform
        and structured_mode == "vllm"
        and ("400" in error or "structured" in error.lower() or "schema" in error.lower())
    ):
        # On context overflow, also shrink max_tokens
        shrink = max_tokens
        if "maximum context length" in error or "input_tokens" in error:
            shrink = min(max_tokens, 192)
        retry_payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": shrink,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        text, first_token, completion_tokens, error = await _consume(retry_payload)

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


def _persona_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "agent_name": args.agent_name,
        "broker_name": args.broker_name,
        "state_name": args.state_name,
        "effective_date": args.effective_date,
    }


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
    freeform: bool = False,
    use_controller: bool | None = None,
    persona: dict[str, Any] | None = None,
) -> dict[str, Any]:
    use_ctrl = USE_CONTROLLER if use_controller is None else use_controller
    if use_ctrl:
        return await run_scenario_controlled(
            client,
            scenario,
            base_url=base_url,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            context_turns=context_turns,
            freeform=freeform,
            persona=persona or {},
        )

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
            freeform=freeform,
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
            freeform=freeform,
        )
        tr.scenario_id = scenario["id"]
        tr.turn_index = idx

        if tr.error:
            tr.ok = False
            row = turn_to_dict(tr)
            row["user"] = user_text
            row["agent_message"] = extract_spoken_message(tr.text) if tr.text else ""
            turn_results.append(row)
            break

        if freeform:
            spoken = extract_spoken_message(tr.text)
            tr.schema_ok = True
            tr.ok = tr.error is None and bool(spoken)
            tr.parsed = {"message": spoken}
            messages.append({"role": "assistant", "content": spoken})
            row = turn_to_dict(tr)
            row["user"] = user_text
            row["agent_message"] = spoken
            turn_results.append(row)
            continue

        score = score_turn(tr.text, turn.get("expect"))
        tr.score = score
        tr.schema_ok = bool(score.get("schema_ok"))
        tr.parsed = score.get("parsed")
        tr.ok = bool(score.get("ok")) and tr.error is None

        messages.append({"role": "assistant", "content": tr.text})
        if tr.parsed and isinstance(tr.parsed.get("state"), dict):
            prior_state = tr.parsed["state"]

        row = turn_to_dict(tr)
        row["user"] = user_text
        row["agent_message"] = extract_spoken_message(tr.text)
        turn_results.append(row)

    return {
        "id": scenario["id"],
        "description": scenario.get("description"),
        "turns": turn_results,
        "passed": all(t.get("ok") for t in turn_results) and bool(turn_results),
        "controller": False,
    }


async def llm_understand_reply(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    ctrl: CloserController,
    caller_text: str,
) -> Understanding:
    """Ask the LLM what the caller meant; controller then decides the step."""
    messages = [
        {"role": "system", "content": UNDERSTAND_SYSTEM},
        {
            "role": "user",
            "content": build_understand_user(
                step=ctrl.state.get("step") or "intro",
                step_question=ctrl.current_step_question(),
                caller_text=caller_text,
                state=ctrl.state,
                side_chat_active=ctrl.side_chat_active,
                side_chat_depth=ctrl.side_chat_depth,
                anchor_step=ctrl.anchor_step or ctrl.state.get("step"),
            ),
        },
    ]
    tr = await stream_chat(
        client,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=90,
        temperature=0.0,
        structured_mode="prompt",
        freeform=True,
    )
    if tr.error:
        # Soft fallback — still try to keep the call moving intelligently via offline
        return offline_understanding(
            ctrl.state.get("step") or "intro", caller_text, ctrl.state
        )
    return parse_understanding(tr.text or "")


async def run_scenario_controlled(
    client: httpx.AsyncClient,
    scenario: dict[str, Any],
    *,
    base_url: str,
    model: str,
    max_tokens: int,
    temperature: float,
    context_turns: int,
    freeform: bool = False,
    persona: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Controller owns action/next/state; LLM only speaks."""
    persona = persona or {}
    ctrl = CloserController(
        effective_date=persona.get("effective_date") or DEFAULT_EFFECTIVE_DATE
    )
    voice_system = build_voice_system_prompt(
        agent_name=persona.get("agent_name") or "Alex",
        broker_name=persona.get("broker_name") or "Summit Senior Advisors",
        state_name=persona.get("state_name") or "Texas",
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": voice_system}]
    turn_results: list[dict[str, Any]] = []

    for idx, turn in enumerate(scenario["turns"]):
        user_text = turn.get("user") or ""
        is_opening = idx == 0 and not str(user_text).strip()

        if is_opening:
            directive = ctrl.opening()
        else:
            if USE_LLM_UNDERSTAND:
                understanding = await llm_understand_reply(
                    client,
                    base_url=base_url,
                    model=model,
                    ctrl=ctrl,
                    caller_text=user_text,
                )
                directive = ctrl.handle(user_text, understanding=understanding)
            else:
                directive = ctrl.handle(user_text)

        voice_user = build_voice_turn_user(
            directive=directive,
            caller_text=user_text,
            is_opening=is_opening,
        )
        messages.append({"role": "user", "content": voice_user})
        messages = trim_messages(messages, context_turns=context_turns)

        tr = await stream_chat(
            client,
            base_url=base_url,
            model=model,
            messages=messages,
            max_tokens=min(max_tokens, 220),
            temperature=max(temperature, 0.55) if freeform else max(temperature, 0.4),
            structured_mode="prompt",
            freeform=True,
        )
        tr.scenario_id = scenario["id"]
        tr.turn_index = idx

        spoken = extract_spoken_message(tr.text) if tr.text else ""
        # Fallback template if model blank
        if not spoken and not tr.error:
            spoken = _fallback_line(directive)

        assembled = assemble_response(directive, spoken)
        raw_json = json.dumps(assembled, ensure_ascii=False)
        tr.text = spoken if freeform else raw_json
        tr.parsed = assembled

        if tr.error:
            tr.ok = False
            row = turn_to_dict(tr)
            row["user"] = user_text
            row["agent_message"] = spoken
            turn_results.append(row)
            break

        if freeform:
            tr.schema_ok = True
            tr.ok = bool(spoken)
            messages.append({"role": "assistant", "content": spoken})
            row = turn_to_dict(tr)
            row["user"] = user_text
            row["agent_message"] = spoken
            row["controller_action"] = directive.action
            row["controller_next"] = directive.next
            turn_results.append(row)
            continue

        # Structured scoring against assembled JSON
        score = score_turn(raw_json, turn.get("expect"))
        tr.score = score
        tr.schema_ok = bool(score.get("schema_ok"))
        tr.ok = bool(score.get("ok")) and tr.error is None
        messages.append({"role": "assistant", "content": spoken})
        row = turn_to_dict(tr)
        row["user"] = user_text
        row["agent_message"] = spoken
        row["controller_action"] = directive.action
        row["controller_next"] = directive.next
        turn_results.append(row)

    return {
        "id": scenario["id"],
        "description": scenario.get("description"),
        "turns": turn_results,
        "passed": all(t.get("ok") for t in turn_results) and bool(turn_results),
        "controller": True,
    }


def _fallback_line(directive) -> str:
    goal = (directive.speech_goal or "").split(".")[0]
    return (goal[:180] + "?") if goal else "Thanks — can I ask you one quick question?"



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


async def mode_correctness(args: argparse.Namespace, *, freeform: bool = False) -> dict[str, Any]:
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    freeform_dir: Path | None = None
    if freeform:
        freeform_dir = RESULTS / f"freeform_{stamp}"
        freeform_dir.mkdir(parents=True, exist_ok=True)
        # Copy judge pack alongside transcripts
        for name in (
            "JUDGE_PROMPT.md",
            "RUBRIC.md",
            "score_template.json",
            "SEND_TO_JUDGE.md",
            "HOW_TO_USE.md",
            "EXPECTED_OUTCOMES.md",
        ):
            src = JUDGE_DIR / name
            if src.exists():
                shutil.copy2(src, freeform_dir / name)
        packets_dir = freeform_dir / "judge_packets"
        packets_dir.mkdir(exist_ok=True)

    async with httpx.AsyncClient(limits=limits) as client:
        model = args.model or await detect_model(client, args.base_url)
        prompt_style = resolve_prompt_style(args.prompt_style, model)
        system_prompt = build_system_prompt(
            **_persona_kwargs(args),
            style=prompt_style,
            model=model,
            freeform=freeform,
        )
        print(f"Model: {model}")
        print(f"Prompt style: {prompt_style}  freeform={freeform}  controller={USE_CONTROLLER}")
        print(f"Running {len(SCENARIOS)} scenarios…")
        scenarios_out: list[dict[str, Any]] = []
        persona = _persona_kwargs(args)
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
                freeform=freeform,
                persona=persona,
            )
            if freeform and freeform_dir is not None:
                write_freeform_transcript(
                    freeform_dir / f"{scenario['id']}.md",
                    scenario_id=scenario["id"],
                    description=scenario.get("description") or "",
                    model=model,
                    turns=result["turns"],
                )
                # Ready-to-paste packet for GPT/Gemini/Claude
                send = (JUDGE_DIR / "SEND_TO_JUDGE.md").read_text(encoding="utf-8")
                transcript = (freeform_dir / f"{scenario['id']}.md").read_text(
                    encoding="utf-8"
                )
                packet = (
                    send.replace(
                        "<<<PASTE THE FULL TRANSCRIPT MARKDOWN BELOW THIS LINE>>>",
                        transcript,
                    )
                    + "\n"
                )
                (packets_dir / f"{scenario['id']}_PASTE_TO_GPT_OR_GEMINI.md").write_text(
                    packet, encoding="utf-8"
                )
                # Freeform: mark passed if all turns produced speech
                result["passed"] = all(
                    t.get("ok") for t in result["turns"]
                ) and bool(result["turns"])
            status = "PASS" if result["passed"] else "FAIL"
            print(f"    {status} ({len(result['turns'])} turns)")
            scenarios_out.append(result)

    all_turns = [t for s in scenarios_out for t in s["turns"]]
    metrics = summarize_turn_metrics(all_turns)
    taxonomy = build_error_taxonomy(scenarios_out) if not freeform else {}
    mode_name = "correctness_freeform" if freeform else "correctness"
    payload = {
        "mode": mode_name,
        "model": model,
        "base_url": args.base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent_name": args.agent_name,
        "broker_name": args.broker_name,
        "prompt_style": prompt_style,
        "structured_mode": args.structured_mode if not freeform else "none",
        "freeform": freeform,
        "use_controller": USE_CONTROLLER,
        "scenarios": scenarios_out,
        "metrics": metrics,
        "error_taxonomy": taxonomy,
        "passed_scenarios": sum(1 for s in scenarios_out if s["passed"]),
        "total_scenarios": len(scenarios_out),
        "freeform_dir": str(freeform_dir) if freeform_dir else None,
    }
    slug = model_slug(model)
    prefix = "closer_freeform" if freeform else "closer_correctness"
    json_path = RESULTS / f"{prefix}_{slug}.json"
    md_path = RESULTS / f"{prefix}_{slug}.md"
    write_json(json_path, payload)
    write_correctness_markdown(md_path, payload)
    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")
    if freeform_dir:
        print(f"Freeform transcripts: {freeform_dir}")
        print("Paste JUDGE_PROMPT.md + a transcript into ChatGPT to score.")
    print(
        f"Scenarios passed: {payload['passed_scenarios']}/{payload['total_scenarios']}  "
        f"turn ok_rate={metrics.get('ok_rate')}"
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
            **_persona_kwargs(args),
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
    json_path = RESULTS / f"closer_stress_turns_{slug}_{concurrency}c.json"
    md_path = RESULTS / f"closer_stress_turns_{slug}_{concurrency}c.md"
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
        persona={
            "agent_name": "Alex",
            "broker_name": "Summit Senior Advisors",
            "state_name": "Texas",
            "effective_date": DEFAULT_EFFECTIVE_DATE,
        },
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
            **_persona_kwargs(args),
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
    json_path = RESULTS / f"closer_stress_sessions_{slug}_{concurrency}c.json"
    md_path = RESULTS / f"closer_stress_sessions_{slug}_{concurrency}c.md"
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
        for wave in range(args.sweep_waves):
            args_ns = argparse.Namespace(**vars(args))
            payload = await mode_stress_sessions(args_ns, concurrency=c, sessions=c)
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
        "metrics": {},
        "structured_mode": args.structured_mode,
        "stop_ttft_ms": args.stop_ttft_ms,
        "stop_min_tps": args.stop_min_tps,
        "max_error_rate": args.max_error_rate,
    }
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
    json_path = RESULTS / f"closer_find_limit_{slug}.json"
    md_path = RESULTS / f"closer_find_limit_{slug}.md"
    write_json(json_path, payload)
    write_stress_markdown(md_path, payload)
    print(f"\nWrote {json_path}")
    print(f"max_stable_concurrency={max_stable}  stop={payload['stop_reason']}")
    return payload


async def mode_interactive(args: argparse.Namespace) -> dict[str, Any]:
    """Terminal REPL — agent speaks first; user types caller lines."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = RESULTS / f"interactive_{stamp}.jsonl"
    persona = _persona_kwargs(args)

    async with httpx.AsyncClient(timeout=300.0) as client:
        model = args.model or await detect_model(client, args.base_url)
        print(f"Model: {model}  controller={USE_CONTROLLER}")
        print(f"Agent: {args.agent_name} @ {args.broker_name}")
        print("Type caller replies. Commands: quit / exit / empty line to end.\n")

        if USE_CONTROLLER:
            ctrl = CloserController(effective_date=persona.get("effective_date") or DEFAULT_EFFECTIVE_DATE)
            voice_system = build_voice_system_prompt(
                agent_name=args.agent_name,
                broker_name=args.broker_name,
                state_name=args.state_name,
            )
            messages: list[dict[str, str]] = [{"role": "system", "content": voice_system}]
            turn_idx = 0
            directive = ctrl.opening()
            voice_max = min(int(args.max_tokens), INTERACTIVE_MAX_TOKENS)
            ctx_turns = min(int(args.context_turns), INTERACTIVE_CONTEXT_TURNS)
            if USE_LLM_UNDERSTAND:
                print(
                    "NOTE: USE_LLM_UNDERSTAND=1 runs a judge LLM before speech — "
                    f"that delays spoken TTFT (target ≤{INTERACTIVE_TARGET_TTFT_MS:.0f}ms). "
                    "Set 0 so speech starts immediately.\n"
                )
            print(
                f"Spoken reply: streamed LLM  |  TTFT target ≤{INTERACTIVE_TARGET_TTFT_MS:.0f}ms  |  "
                f"max_tokens={voice_max}  |  step judge={'llm' if USE_LLM_UNDERSTAND else 'offline'}\n"
            )
            while True:
                if turn_idx == 0:
                    messages.append(
                        {
                            "role": "user",
                            "content": build_voice_turn_user(
                                directive=directive,
                                caller_text="",
                                is_opening=True,
                            ),
                        }
                    )
                messages = trim_messages(messages, context_turns=ctx_turns)
                print("\nAGENT: ", end="", flush=True)
                tr = await stream_chat(
                    client,
                    base_url=args.base_url,
                    model=model,
                    messages=messages,
                    max_tokens=voice_max,
                    temperature=max(args.temperature, 0.45),
                    structured_mode="prompt",
                    freeform=True,
                    on_delta=lambda d: print(d, end="", flush=True),
                )
                print(flush=True)
                if tr.error:
                    print(f"[error] {tr.error}")
                    break
                spoken = extract_spoken_message(tr.text) or _fallback_line(directive)
                if not (tr.text or "").strip():
                    print(spoken, flush=True)
                assembled = assemble_response(directive, spoken)
                ttft = tr.ttft_ms
                over = ttft is not None and ttft > INTERACTIVE_TARGET_TTFT_MS
                print(
                    f"  [ttft={ttft:.0f}ms"
                    f"{' OVER ' + str(int(INTERACTIVE_TARGET_TTFT_MS)) + 'ms' if over else ' OK'}"
                    f" total={tr.total_ms:.0f}ms]"
                    if ttft is not None
                    else f"  [total={tr.total_ms:.0f}ms]"
                )
                if args.debug:
                    print(
                        f"  [debug] action={assembled['action']} next={assembled['next']} "
                        f"step={assembled['state'].get('step')} "
                        f"status={ctrl.last_step_status} "
                        f"side_chat={ctrl.side_chat_active}/{ctrl.side_chat_depth}"
                    )
                messages.append({"role": "assistant", "content": spoken})
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "turn": turn_idx,
                                "agent": spoken,
                                "parsed": assembled,
                                "ttft_ms": tr.ttft_ms,
                                "total_ms": tr.total_ms,
                                "target_ttft_ms": INTERACTIVE_TARGET_TTFT_MS,
                            }
                        )
                        + "\n"
                    )
                if assembled["action"] != "continue":
                    print("\n[call ended]")
                    break
                try:
                    caller = input("\nYOU: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n[session ended]")
                    break
                if not caller or caller.lower() in ("quit", "exit", "q"):
                    print("[session ended]")
                    break
                turn_idx += 1
                with log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"turn": turn_idx, "caller": caller}) + "\n")
                if USE_LLM_UNDERSTAND:
                    understanding = await llm_understand_reply(
                        client,
                        base_url=args.base_url,
                        model=model,
                        ctrl=ctrl,
                        caller_text=caller,
                    )
                else:
                    understanding = offline_understanding(
                        ctrl.state.get("step") or "intro", caller, ctrl.state
                    )
                if args.debug:
                    print(
                        f"  [understand] status={understanding.step_status} "
                        f"kind={understanding.kind} advance={understanding.advance} "
                        f"side_chat={ctrl.side_chat_active}/{ctrl.side_chat_depth} "
                        f"interrupt={understanding.interrupt} facts={understanding.facts} "
                        f"via={'llm' if USE_LLM_UNDERSTAND else 'offline'}"
                    )
                directive = ctrl.handle(caller, understanding=understanding)
                messages.append(
                    {
                        "role": "user",
                        "content": build_voice_turn_user(
                            directive=directive,
                            caller_text=caller,
                            is_opening=False,
                        ),
                    }
                )
            print(f"Log: {log_path}")
            return {"log": str(log_path), "model": model, "controller": True}

        # Legacy non-controller path
        freeform = not args.structured
        prompt_style = resolve_prompt_style(args.prompt_style, model)
        system_prompt = build_system_prompt(
            **persona,
            style=prompt_style,
            model=model,
            freeform=freeform,
        )
        messages = [{"role": "system", "content": system_prompt}]
        prior_state: dict[str, Any] | None = None
        turn_idx = 0
        user_content = build_turn_user_content(
            user_text="", prior_state=prior_state, is_opening=True, freeform=freeform
        )
        messages.append({"role": "user", "content": user_content})
        while True:
            messages = trim_messages(messages, context_turns=args.context_turns)
            tr = await stream_chat(
                client,
                base_url=args.base_url,
                model=model,
                messages=messages,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                structured_mode=args.structured_mode,
                freeform=freeform,
            )
            if tr.error:
                print(f"[error] {tr.error}")
                break
            spoken = extract_spoken_message(tr.text)
            print(f"\nAGENT: {spoken}")
            parsed = None
            if args.structured:
                score = score_turn(tr.text, expect=None)
                parsed = score.get("parsed")
                if args.debug and parsed:
                    print(
                        f"  [debug] action={parsed.get('action')} next={parsed.get('next')} "
                        f"step={(parsed.get('state') or {}).get('step')}"
                    )
                if parsed and isinstance(parsed.get("state"), dict):
                    prior_state = parsed["state"]
                messages.append({"role": "assistant", "content": tr.text})
            else:
                messages.append({"role": "assistant", "content": spoken})
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"turn": turn_idx, "agent": spoken, "parsed": parsed}) + "\n")
            if parsed and parsed.get("action") in (
                "enroll_success",
                "close_optimal_current",
                "close_not_decision_maker",
                "close_employer_conflict",
                "callback",
                "dnc",
                "end_abuse",
            ):
                print("\n[call ended]")
                break
            try:
                caller = input("\nYOU: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[session ended]")
                break
            if not caller or caller.lower() in ("quit", "exit", "q"):
                print("[session ended]")
                break
            turn_idx += 1
            messages.append(
                {
                    "role": "user",
                    "content": build_turn_user_content(
                        user_text=caller,
                        prior_state=prior_state,
                        is_opening=False,
                        freeform=freeform,
                    ),
                }
            )
        print(f"Log: {log_path}")
        return {"log": str(log_path), "model": model, "controller": False}


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
    print(f"  TPS avg/min: {metrics.get('tps_avg')}/{metrics.get('tps_min')}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Medicare closer LLM stress/correctness")
    p.add_argument(
        "mode",
        choices=[
            "correctness",
            "correctness_freeform",
            "interactive",
            "stress_turns",
            "stress_sessions",
            "find_limit",
        ],
    )
    p.add_argument("--base-url", default=os.getenv("BASE_URL", "http://127.0.0.1:8000"))
    p.add_argument("--model", default=os.getenv("MODEL") or None)
    p.add_argument("--agent-name", default=os.getenv("AGENT_NAME", "Alex"))
    p.add_argument(
        "--broker-name",
        default=os.getenv("BROKER_NAME", "Summit Senior Advisors"),
    )
    p.add_argument("--state-name", default=os.getenv("STATE_NAME", "Texas"))
    p.add_argument(
        "--effective-date",
        default=os.getenv("EFFECTIVE_DATE", DEFAULT_EFFECTIVE_DATE),
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
    )
    p.add_argument("--max-tokens", type=int, default=int(os.getenv("MAX_TOKENS", "384")))
    p.add_argument(
        "--temperature", type=float, default=float(os.getenv("TEMPERATURE", "0.1"))
    )
    p.add_argument(
        "--context-turns", type=int, default=int(os.getenv("CONTEXT_TURNS", "4"))
    )
    p.add_argument(
        "--concurrency", type=int, default=int(os.getenv("CONCURRENCY", "5"))
    )
    p.add_argument("--requests", type=int, default=int(os.getenv("REQUESTS", "10")))
    p.add_argument("--sessions", type=int, default=int(os.getenv("SESSIONS", "5")))
    p.add_argument(
        "--sweep-start", type=int, default=int(os.getenv("SWEEP_START", "1"))
    )
    p.add_argument("--sweep-max", type=int, default=int(os.getenv("SWEEP_MAX", "40")))
    p.add_argument("--sweep-step", type=int, default=int(os.getenv("SWEEP_STEP", "5")))
    p.add_argument(
        "--sweep-waves", type=int, default=int(os.getenv("SWEEP_WAVES", "1"))
    )
    p.add_argument(
        "--stop-ttft-ms",
        type=float,
        default=float(os.getenv("STOP_TTFT_MS", "2500")),
    )
    p.add_argument(
        "--stop-min-tps",
        type=float,
        default=float(os.getenv("STOP_MIN_TPS", "3")),
    )
    p.add_argument(
        "--max-error-rate",
        type=float,
        default=float(os.getenv("MAX_ERROR_RATE", "0.08")),
    )
    # interactive flags
    p.add_argument(
        "--structured",
        action="store_true",
        help="Interactive: use JSON structured mode instead of freeform speech",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Interactive structured: print action/next/step each turn",
    )
    return p


async def async_main(args: argparse.Namespace) -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.mode == "correctness":
        await mode_correctness(args, freeform=False)
    elif args.mode == "correctness_freeform":
        await mode_correctness(args, freeform=True)
    elif args.mode == "interactive":
        # Higher temp default for freeform interactive if still at harness default
        if not args.structured and abs(args.temperature - 0.1) < 1e-9:
            args.temperature = float(os.getenv("INTERACTIVE_TEMPERATURE", "0.6"))
        await mode_interactive(args)
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
