"""Validate closer JSON against schema expectations and state-machine rules."""

from __future__ import annotations

from typing import Any

from plans import PLAN_IDS
from schema import CLOSE_ACTIONS, TERMINAL_ACTIONS, parse_closer_response


def _message_matches(message: str, needles: list[str]) -> bool:
    lower = message.lower()
    return any(n.lower() in lower for n in needles)


def validate_against_expect(
    parsed: dict[str, Any],
    expect: dict[str, Any] | None,
) -> dict[str, Any]:
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
        "decision_maker",
        "callback_ok",
        "medicare_permission",
        "nursing_home",
        "soa_agreed",
        "voice_signed",
        "other_coverage",
        "selected_plan_id",
        "current_plan",
        "caller_name",
        "zip",
        "dob",
        "priorities",
        "effective_date",
    ):
        if key in expect and state.get(key) != expect[key]:
            state_ok = False
            errors.append(
                f"state.{key} expected {expect[key]!r} got {state.get(key)!r}"
            )

    if "conditions_any" in expect:
        conds = [c.lower() for c in (state.get("conditions") or [])]
        joined = " ".join(conds)
        needles = [n.lower() for n in expect["conditions_any"]]
        ok = any(n in joined for n in needles)
        if not ok:
            state_ok = False
            errors.append(
                f"state.conditions missing any of {expect['conditions_any']}: {conds!r}"
            )

    if "dnc" in expect and flags.get("dnc") != expect["dnc"]:
        flags_ok = False
        errors.append(f"flags.dnc expected {expect['dnc']!r}")
    if "abuse" in expect and flags.get("abuse") != expect["abuse"]:
        flags_ok = False
        errors.append(f"flags.abuse expected {expect['abuse']!r}")
    if "medicaid_dual" in expect and flags.get("medicaid_dual") != expect["medicaid_dual"]:
        flags_ok = False
        errors.append(f"flags.medicaid_dual expected {expect['medicaid_dual']!r}")
    if "side_topic" in expect and flags.get("side_topic") != expect["side_topic"]:
        errors.append(f"flags.side_topic expected {expect['side_topic']!r} (soft)")

    if "message_any" in expect:
        if not _message_matches(message, expect["message_any"]):
            message_ok = False
            errors.append(
                f"message missing any of {expect['message_any']}: {message[:160]!r}"
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

    if action == "continue" and next_val == "done":
        errors.append("action=continue should not have next=done")

    if action == "enroll_success":
        if state.get("soa_agreed") is not True:
            errors.append("enroll_success requires soa_agreed=true")
        if state.get("voice_signed") is not True:
            errors.append("enroll_success requires voice_signed=true")
        sp = state.get("selected_plan_id")
        if sp not in PLAN_IDS:
            errors.append(
                f"enroll_success requires selected_plan_id in {PLAN_IDS}, got {sp!r}"
            )
        if state.get("other_coverage") == "employer":
            errors.append("enroll_success forbidden when other_coverage=employer")
        if state.get("decision_maker") is False:
            errors.append("enroll_success forbidden when decision_maker=false")

    # Hard gate: no plan pitch / selection before SOA
    if action == "continue":
        sp = state.get("selected_plan_id")
        nxt = next_val
        if state.get("soa_agreed") is not True and (
            sp in PLAN_IDS
            or nxt
            in (
                "plan_review",
                "dual_attestation",
                "plan_confirm",
                "enrollment_readback",
                "voice_signature",
            )
        ):
            errors.append("cannot pitch or select a plan before soa_agreed=true")

    if action == "close_employer_conflict":
        if state.get("other_coverage") not in ("employer", None):
            # allow None after normalize sets employer
            pass
        if state.get("other_coverage") and state.get("other_coverage") != "employer":
            errors.append(
                "close_employer_conflict expects other_coverage=employer "
                f"got {state.get('other_coverage')!r}"
            )

    if action == "close_not_decision_maker":
        if state.get("decision_maker") is True:
            errors.append("close_not_decision_maker inconsistent with decision_maker=true")

    sp = state.get("selected_plan_id")
    if sp is not None and sp not in PLAN_IDS:
        errors.append(f"selected_plan_id {sp!r} not in catalog")

    if (
        sp == "dual_food_snp"
        and action == "enroll_success"
        and not flags.get("medicaid_dual")
    ):
        # soft-ish hard rule: dual plan should mark medicaid_dual
        errors.append("enroll on dual_food_snp should set flags.medicaid_dual=true")

    if flags.get("side_topic") and action == "continue" and next_val == "done":
        errors.append("side_topic continue should not set next=done")

    if action in CLOSE_ACTIONS and state.get("step") not in (
        "close",
        "close_success",
        "intro",
        "disclaimers",
        "soa",
        "ask_decision_maker",
        "ask_other_coverage",
        "plan_review",
        "ask_callback",
    ):
        # allow various steps when closing early
        pass

    return errors


def score_turn(
    raw_text: str,
    expect: dict[str, Any] | None = None,
    *,
    require_state_machine: bool = True,
) -> dict[str, Any]:
    parsed, schema_ok, schema_errors = parse_closer_response(raw_text)
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
