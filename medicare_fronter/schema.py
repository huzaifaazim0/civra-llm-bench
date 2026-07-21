"""Medicare fronter JSON response schema and parse helpers."""

from __future__ import annotations

import json
import re
from typing import Any

STEPS = (
    "intro",
    "await_time",
    "ask_parts",
    "ask_age",
    "ask_disability",
    "transfer",
    "close",
)

NEXT_VALUES = STEPS + ("done",)

ACTIONS = (
    "continue",
    "transfer",
    "close_no_time",
    "close_no_parts",
    "close_ineligible",
    "dnc",
    "end_abuse",
)

CLOSE_ACTIONS = frozenset(
    {"close_no_time", "close_no_parts", "close_ineligible", "dnc", "end_abuse"}
)

TERMINAL_ACTIONS = frozenset({"transfer"} | CLOSE_ACTIONS)

FRONTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "state": {
            "type": "object",
            "properties": {
                "step": {"type": "string", "enum": list(STEPS)},
                "has_time": {"type": ["boolean", "null"]},
                "has_part_a": {"type": ["boolean", "null"]},
                "has_part_b": {"type": ["boolean", "null"]},
                "age": {"type": ["integer", "null"]},
                "has_disability": {"type": ["boolean", "null"]},
                "eligible": {"type": ["boolean", "null"]},
                "flags": {
                    "type": "object",
                    "properties": {
                        "dnc": {"type": "boolean"},
                        "abuse": {"type": "boolean"},
                        "side_topic": {"type": "boolean"},
                    },
                    "required": ["dnc", "abuse", "side_topic"],
                },
            },
            "required": [
                "step",
                "has_time",
                "has_part_a",
                "has_part_b",
                "age",
                "has_disability",
                "eligible",
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
        "has_time": None,
        "has_part_a": None,
        "has_part_b": None,
        "age": None,
        "has_disability": None,
        "eligible": None,
        "flags": {"dnc": False, "abuse": False, "side_topic": False},
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


def _is_int_or_null(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, bool):
        return False
    return isinstance(v, int)


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
    for key in ("has_time", "has_part_a", "has_part_b", "has_disability", "eligible"):
        if not _is_bool_or_null(state.get(key)):
            errors.append(f"state.{key} must be boolean or null")
    if not _is_int_or_null(state.get("age")):
        errors.append("state.age must be integer or null")

    flags = state.get("flags")
    if not isinstance(flags, dict):
        errors.append("state.flags must be an object")
    else:
        for key in ("dnc", "abuse", "side_topic"):
            if not isinstance(flags.get(key), bool):
                errors.append(f"state.flags.{key} must be boolean")

    return len(errors) == 0, errors


def normalize_fronter_response(obj: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize common valid-but-sloppy model outputs before scoring.

    Models often set next=transfer/close instead of next=done on terminal
    actions, leave eligible null when transferring, or set both dnc+abuse.
    """
    out = json.loads(json.dumps(obj))  # deep copy via JSON
    action = out.get("action")
    state = out.get("state") if isinstance(out.get("state"), dict) else {}
    flags = state.get("flags") if isinstance(state.get("flags"), dict) else {}
    out["state"] = state
    state["flags"] = flags

    # Coerce age from numeric strings / floats
    age = state.get("age")
    if isinstance(age, float) and age == int(age):
        state["age"] = int(age)
    elif isinstance(age, str) and age.strip().isdigit():
        state["age"] = int(age.strip())

    # Terminal actions: next must be done; align step
    if action == "transfer":
        out["next"] = "done"
        state["step"] = "transfer"
        age_i = state.get("age")
        if (isinstance(age_i, int) and age_i >= 65) or state.get("has_disability") is True:
            state["eligible"] = True
    elif action in CLOSE_ACTIONS:
        out["next"] = "done"
        state["step"] = "close"
        if action == "close_no_time" and state.get("has_time") is None:
            state["has_time"] = False
        if action == "close_no_parts":
            if state.get("has_part_a") is None:
                state["has_part_a"] = False
            if state.get("has_part_b") is None:
                state["has_part_b"] = False
        if action == "close_ineligible" and state.get("eligible") is None:
            state["eligible"] = False
        if action == "dnc":
            flags["dnc"] = True
            # Keep abuse if already set — dual flags are allowed
        if action == "end_abuse":
            flags["abuse"] = True
            # Keep dnc if already set — dual flags are allowed

    # Dual DNC+abuse flags are acceptable when action is end_abuse or dnc.
    # Do not clear the other flag.

    # Continue should not claim done
    if action == "continue" and out.get("next") == "done":
        step = state.get("step")
        if step in STEPS and step not in ("transfer", "close"):
            out["next"] = step

    return out


def parse_fronter_response(text: str) -> tuple[dict[str, Any] | None, bool, list[str]]:
    obj = extract_json_object(text)
    if obj is None:
        return None, False, ["unparseable JSON"]
    ok, errors = validate_schema_shape(obj)
    if not ok or obj is None:
        return obj, ok, errors
    normalized = normalize_fronter_response(obj)
    ok2, errors2 = validate_schema_shape(normalized)
    return normalized, ok2, errors2 if not ok2 else errors
