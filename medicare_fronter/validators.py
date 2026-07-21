"""Validate fronter JSON against schema expectations and state-machine rules."""

from __future__ import annotations

from typing import Any

from schema import (
    CLOSE_ACTIONS,
    TERMINAL_ACTIONS,
    parse_fronter_response,
)


def _message_matches(message: str, needles: list[str]) -> bool:
    lower = message.lower()
    return any(n.lower() in lower for n in needles)


def validate_against_expect(
    parsed: dict[str, Any],
    expect: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare model output to scenario expect dict. Returns check flags + errors."""
    errors: list[str] = []
    action_ok = True
    next_ok = True
    state_ok = True
    message_ok = True
    flags_ok = True

    if not expect:
        return {
            "action_ok": True,
            "next_ok": True,
            "state_ok": True,
            "message_ok": True,
            "flags_ok": True,
            "errors": [],
        }

    action = parsed.get("action")
    next_val = parsed.get("next")
    state = parsed.get("state") or {}
    flags = state.get("flags") or {}
    message = parsed.get("message") or ""

    if "action" in expect and action != expect["action"]:
        action_ok = False
        errors.append(f"action expected {expect['action']!r} got {action!r}")
    if "actions" in expect and action not in expect["actions"]:
        action_ok = False
        errors.append(f"action expected one of {expect['actions']} got {action!r}")

    if "next" in expect and next_val != expect["next"]:
        next_ok = False
        errors.append(f"next expected {expect['next']!r} got {next_val!r}")
    if "nexts" in expect and next_val not in expect["nexts"]:
        next_ok = False
        errors.append(f"next expected one of {expect['nexts']} got {next_val!r}")

    if "step" in expect and state.get("step") != expect["step"]:
        state_ok = False
        errors.append(f"step expected {expect['step']!r} got {state.get('step')!r}")

    for key in (
        "has_time",
        "has_part_a",
        "has_part_b",
        "has_disability",
        "eligible",
    ):
        if key in expect and state.get(key) != expect[key]:
            state_ok = False
            errors.append(f"state.{key} expected {expect[key]!r} got {state.get(key)!r}")

    if "age" in expect:
        got_age = state.get("age")
        if got_age != expect["age"]:
            # allow nearby ages if model parsed differently — still fail exact
            state_ok = False
            errors.append(f"state.age expected {expect['age']!r} got {got_age!r}")

    if "dnc" in expect and flags.get("dnc") != expect["dnc"]:
        flags_ok = False
        errors.append(f"flags.dnc expected {expect['dnc']!r}")
    if "abuse" in expect and flags.get("abuse") != expect["abuse"]:
        flags_ok = False
        errors.append(f"flags.abuse expected {expect['abuse']!r}")
    # side_topic flag is soft — models often re-ask correctly without setting it
    if "side_topic" in expect and flags.get("side_topic") != expect["side_topic"]:
        errors.append(f"flags.side_topic expected {expect['side_topic']!r} (soft)")

    if "message_any" in expect:
        if not _message_matches(message, expect["message_any"]):
            message_ok = False
            errors.append(
                f"message missing any of {expect['message_any']}: {message[:120]!r}"
            )

    return {
        "action_ok": action_ok,
        "next_ok": next_ok,
        "state_ok": state_ok,
        "message_ok": message_ok,
        "flags_ok": flags_ok,
        "errors": errors,
    }


def validate_state_machine(parsed: dict[str, Any]) -> list[str]:
    """Hard consistency rules independent of scenario expects."""
    errors: list[str] = []
    action = parsed.get("action")
    next_val = parsed.get("next")
    state = parsed.get("state") or {}
    flags = state.get("flags") or {}
    age = state.get("age")
    eligible = state.get("eligible")
    has_disability = state.get("has_disability")
    has_time = state.get("has_time")
    has_a = state.get("has_part_a")
    has_b = state.get("has_part_b")

    # Dual DNC+abuse flags are OK when ending via dnc or end_abuse.
    if action == "dnc" and not flags.get("dnc"):
        errors.append("action=dnc requires flags.dnc=true")
    if action == "end_abuse" and not flags.get("abuse"):
        errors.append("action=end_abuse requires flags.abuse=true")
    if flags.get("dnc") and action not in ("dnc", "end_abuse"):
        errors.append("flags.dnc=true requires action=dnc or end_abuse")
    if flags.get("abuse") and action not in ("end_abuse", "dnc"):
        errors.append("flags.abuse=true requires action=end_abuse or dnc")

    if action in TERMINAL_ACTIONS and next_val != "done":
        errors.append(f"terminal action {action} requires next=done")

    if action == "transfer":
        if eligible is not True:
            errors.append("action=transfer requires eligible=true")
        age_ok = isinstance(age, int) and age >= 65
        disability_ok = has_disability is True
        if not (age_ok or disability_ok):
            errors.append(
                "action=transfer requires age>=65 or has_disability=true"
            )

    if action == "close_ineligible":
        if eligible is True:
            errors.append("close_ineligible cannot have eligible=true")
        if isinstance(age, int) and age >= 65:
            errors.append("close_ineligible unexpected for age>=65")
        if isinstance(age, int) and age < 65 and has_disability is None:
            errors.append(
                "close_ineligible when age<65 requires has_disability true/false first"
            )

    if action == "close_no_time" and has_time is True:
        errors.append("close_no_time inconsistent with has_time=true")

    if action == "close_no_parts" and has_a is True and has_b is True:
        errors.append("close_no_parts inconsistent with both parts true")

    if action == "continue" and next_val == "done":
        errors.append("action=continue should not have next=done")

    if action in CLOSE_ACTIONS and state.get("step") not in ("close", "transfer", "intro", "await_time", "ask_parts", "ask_age", "ask_disability"):
        errors.append(f"unexpected step {state.get('step')} for close action")

    # Side topic should not jump to transfer/done unless also terminal flags
    if flags.get("side_topic") and action == "continue" and next_val == "done":
        errors.append("side_topic continue should not set next=done")

    return errors


def score_turn(
    raw_text: str,
    expect: dict[str, Any] | None = None,
    *,
    require_state_machine: bool = True,
) -> dict[str, Any]:
    parsed, schema_ok, schema_errors = parse_fronter_response(raw_text)
    result: dict[str, Any] = {
        "schema_ok": schema_ok,
        "schema_errors": schema_errors,
        "parsed": parsed,
        "state_machine_ok": True,
        "state_machine_errors": [],
        "action_ok": False,
        "next_ok": False,
        "state_ok": False,
        "message_ok": False,
        "flags_ok": False,
        "expect_errors": [],
        "ok": False,
    }
    if not schema_ok or parsed is None:
        return result

    sm_errors = validate_state_machine(parsed) if require_state_machine else []
    result["state_machine_errors"] = sm_errors
    result["state_machine_ok"] = len(sm_errors) == 0

    expect_result = validate_against_expect(parsed, expect)
    result.update(
        {
            "action_ok": expect_result["action_ok"],
            "next_ok": expect_result["next_ok"],
            "state_ok": expect_result["state_ok"],
            "message_ok": expect_result["message_ok"],
            "flags_ok": expect_result["flags_ok"],
            "expect_errors": expect_result["errors"],
        }
    )

    # Soft message check: do not fail overall solely on message_ok
    hard_ok = (
        schema_ok
        and result["state_machine_ok"]
        and result["action_ok"]
        and result["next_ok"]
        and result["state_ok"]
        and result["flags_ok"]
    )
    result["ok"] = hard_ok
    result["ok_strict"] = hard_ok and result["message_ok"]
    return result
