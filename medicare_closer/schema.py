"""Medicare closer JSON response schema and parse helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from plans import PLAN_IDS

STEPS = (
    "intro",
    "disclaimers",
    "soa",
    "ask_decision_maker",
    "ask_callback",
    "verify_zip",
    "verify_dob",
    "medicare_permission",
    "ask_satisfaction",
    "ask_conditions",
    "ask_doctor",
    "ask_meds",
    "ask_priorities",
    "ask_living",
    "ask_other_coverage",
    "plan_review",
    "dual_attestation",
    "plan_confirm",
    "address",
    "enrollment_readback",
    "voice_signature",
    "close_success",
    "close",
)

NEXT_VALUES = STEPS + ("done",)

ACTIONS = (
    "continue",
    "enroll_success",
    "close_optimal_current",
    "close_not_decision_maker",
    "close_employer_conflict",
    "callback",
    "dnc",
    "end_abuse",
)

CLOSE_ACTIONS = frozenset(
    {
        "close_optimal_current",
        "close_not_decision_maker",
        "close_employer_conflict",
        "callback",
        "dnc",
        "end_abuse",
    }
)

TERMINAL_ACTIONS = frozenset({"enroll_success"} | CLOSE_ACTIONS)

OTHER_COVERAGE = ("none", "employer", "va", "tricare", None)

CLOSER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "state": {
            "type": "object",
            "properties": {
                "step": {"type": "string", "enum": list(STEPS)},
                "caller_name": {"type": ["string", "null"]},
                "decision_maker": {"type": ["boolean", "null"]},
                "callback_ok": {"type": ["boolean", "null"]},
                "zip": {"type": ["string", "null"]},
                "dob": {"type": ["string", "null"]},
                "medicare_permission": {"type": ["boolean", "null"]},
                "current_plan": {"type": ["string", "null"]},
                "conditions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "doctor": {"type": ["string", "null"]},
                "meds": {"type": ["string", "null"]},
                "priorities": {"type": ["string", "null"]},
                "nursing_home": {"type": ["boolean", "null"]},
                "other_coverage": {
                    "type": ["string", "null"],
                    "description": "none | employer | va | tricare | null",
                },
                "selected_plan_id": {
                    "type": ["string", "null"],
                    "description": "giveback_ppo | otc_zero | dual_food_snp | null",
                },
                "effective_date": {"type": ["string", "null"]},
                "soa_agreed": {"type": ["boolean", "null"]},
                "voice_signed": {"type": ["boolean", "null"]},
                "flags": {
                    "type": "object",
                    "properties": {
                        "dnc": {"type": "boolean"},
                        "abuse": {"type": "boolean"},
                        "side_topic": {"type": "boolean"},
                        "medicaid_dual": {"type": "boolean"},
                    },
                    "required": ["dnc", "abuse", "side_topic", "medicaid_dual"],
                },
            },
            "required": [
                "step",
                "caller_name",
                "decision_maker",
                "callback_ok",
                "zip",
                "dob",
                "medicare_permission",
                "current_plan",
                "conditions",
                "doctor",
                "meds",
                "priorities",
                "nursing_home",
                "other_coverage",
                "selected_plan_id",
                "effective_date",
                "soa_agreed",
                "voice_signed",
                "flags",
            ],
        },
        "next": {"type": "string", "enum": list(NEXT_VALUES)},
        "action": {"type": "string", "enum": list(ACTIONS)},
    },
    "required": ["message", "state", "next", "action"],
}


def empty_state(step: str = "intro") -> dict[str, Any]:
    return {
        "step": step,
        "caller_name": None,
        "decision_maker": None,
        "callback_ok": None,
        "zip": None,
        "dob": None,
        "medicare_permission": None,
        "current_plan": None,
        "conditions": [],
        "doctor": None,
        "meds": None,
        "priorities": None,
        "nursing_home": None,
        "other_coverage": None,
        "selected_plan_id": None,
        "effective_date": None,
        "soa_agreed": None,
        "voice_signed": None,
        "flags": {
            "dnc": False,
            "abuse": False,
            "side_topic": False,
            "medicaid_dual": False,
        },
    }


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from model text (raw or fenced)."""
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(cleaned[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _is_bool_or_null(v: Any) -> bool:
    return v is None or isinstance(v, bool)


def _is_str_or_null(v: Any) -> bool:
    return v is None or isinstance(v, str)


def validate_schema_shape(obj: dict[str, Any]) -> tuple[bool, list[str]]:
    """Lightweight schema check without external deps."""
    errors: list[str] = []
    if not isinstance(obj.get("message"), str) or not obj["message"].strip():
        errors.append("message must be a non-empty string")
    if obj.get("next") not in NEXT_VALUES:
        errors.append(f"next must be one of {NEXT_VALUES}")
    if obj.get("action") not in ACTIONS:
        errors.append(f"action must be one of {ACTIONS}")

    state = obj.get("state")
    if not isinstance(state, dict):
        errors.append("state must be an object")
        return False, errors

    if state.get("step") not in STEPS:
        errors.append(f"state.step must be one of {STEPS}")

    for key in (
        "decision_maker",
        "callback_ok",
        "medicare_permission",
        "nursing_home",
        "soa_agreed",
        "voice_signed",
    ):
        if not _is_bool_or_null(state.get(key)):
            errors.append(f"state.{key} must be boolean or null")

    for key in (
        "caller_name",
        "zip",
        "dob",
        "current_plan",
        "doctor",
        "meds",
        "priorities",
        "effective_date",
    ):
        if not _is_str_or_null(state.get(key)):
            errors.append(f"state.{key} must be string or null")

    conditions = state.get("conditions")
    if conditions is None:
        state["conditions"] = []
        conditions = state["conditions"]
    if not isinstance(conditions, list):
        errors.append("state.conditions must be an array")
    elif not all(isinstance(c, str) for c in conditions):
        errors.append("state.conditions items must be strings")

    oc = state.get("other_coverage")
    if oc is not None and oc not in ("none", "employer", "va", "tricare"):
        errors.append(
            "state.other_coverage must be none|employer|va|tricare|null"
        )

    sp = state.get("selected_plan_id")
    if sp is not None and sp not in PLAN_IDS:
        errors.append(f"state.selected_plan_id must be one of {PLAN_IDS} or null")

    flags = state.get("flags")
    if not isinstance(flags, dict):
        errors.append("state.flags must be an object")
    else:
        for key in ("dnc", "abuse", "side_topic", "medicaid_dual"):
            if not isinstance(flags.get(key), bool):
                errors.append(f"state.flags.{key} must be boolean")

    return len(errors) == 0, errors


def normalize_closer_response(obj: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize common valid-but-sloppy model outputs before scoring."""
    out = json.loads(json.dumps(obj))
    action = out.get("action")
    state = out.get("state") if isinstance(out.get("state"), dict) else {}
    flags = state.get("flags") if isinstance(state.get("flags"), dict) else {}
    out["state"] = state
    state["flags"] = flags

    if not isinstance(state.get("conditions"), list):
        state["conditions"] = []

    # Ensure flag defaults
    for key in ("dnc", "abuse", "side_topic", "medicaid_dual"):
        if not isinstance(flags.get(key), bool):
            flags[key] = False

    if action == "enroll_success":
        out["next"] = "done"
        state["step"] = "close_success"
        if state.get("voice_signed") is None:
            state["voice_signed"] = True
        if state.get("soa_agreed") is None:
            state["soa_agreed"] = True
    elif action in CLOSE_ACTIONS:
        out["next"] = "done"
        state["step"] = "close"
        if action == "dnc":
            flags["dnc"] = True
        if action == "end_abuse":
            flags["abuse"] = True
        if action == "close_not_decision_maker" and state.get("decision_maker") is None:
            state["decision_maker"] = False
        if action == "close_employer_conflict" and state.get("other_coverage") is None:
            state["other_coverage"] = "employer"

    if action == "continue" and out.get("next") == "done":
        step = state.get("step")
        if step in STEPS and step not in ("close", "close_success"):
            out["next"] = step

    # Coerce selected_plan_id typos
    sp = state.get("selected_plan_id")
    if isinstance(sp, str):
        sp_l = sp.strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {
            "giveback": "giveback_ppo",
            "giveback_ppo": "giveback_ppo",
            "otc": "otc_zero",
            "otc_zero": "otc_zero",
            "dual": "dual_food_snp",
            "dual_food": "dual_food_snp",
            "dual_food_snp": "dual_food_snp",
            "dual_snp": "dual_food_snp",
        }
        if sp_l in aliases:
            state["selected_plan_id"] = aliases[sp_l]
            sp = state["selected_plan_id"]

    # Dual SNP implies medicaid dual flag
    if sp == "dual_food_snp":
        flags["medicaid_dual"] = True

    # Normalize other_coverage casing / aliases
    oc = state.get("other_coverage")
    if isinstance(oc, str):
        oc_l = oc.strip().lower().replace(" ", "_")
        oc_map = {
            "none": "none",
            "no": "none",
            "employer": "employer",
            "job": "employer",
            "work": "employer",
            "retiree": "employer",
            "va": "va",
            "veterans": "va",
            "tricare": "tricare",
        }
        if oc_l in oc_map:
            state["other_coverage"] = oc_map[oc_l]

    # Continue must not carry terminal DNC/abuse flags (models often set both)
    if action == "continue":
        if flags.get("dnc") or flags.get("abuse"):
            flags["dnc"] = False
            flags["abuse"] = False

    # Cannot pitch/select plan before SOA
    plan_steps = {
        "plan_review",
        "dual_attestation",
        "plan_confirm",
        "address",
        "enrollment_readback",
        "voice_signature",
        "close_success",
    }
    if state.get("soa_agreed") is not True:
        if state.get("selected_plan_id") is not None and action == "continue":
            state["selected_plan_id"] = None
        if out.get("next") in plan_steps and action == "continue":
            out["next"] = "soa" if state.get("soa_agreed") is not True else out["next"]
            if state.get("step") in plan_steps:
                state["step"] = "soa"

    return out


def parse_closer_response(text: str) -> tuple[dict[str, Any] | None, bool, list[str]]:
    obj = extract_json_object(text)
    if obj is None:
        return None, False, ["unparseable JSON"]
    ok, errors = validate_schema_shape(obj)
    if not ok:
        # Still try normalize then re-validate
        try:
            normalized = normalize_closer_response(obj)
            ok2, errors2 = validate_schema_shape(normalized)
            return normalized, ok2, errors2 if not ok2 else errors
        except Exception:  # noqa: BLE001
            return obj, False, errors
    normalized = normalize_closer_response(obj)
    ok2, errors2 = validate_schema_shape(normalized)
    return normalized, ok2, errors2 if not ok2 else errors
