"""Scripted multi-turn Medicare fronter conversation scenarios."""

from __future__ import annotations

from typing import Any

# Each turn: user utterance ("" = opening / model speaks first), plus expectations.
# expect keys are optional soft checks used by validators.


def _expect(
    *,
    action: str | None = None,
    next: str | None = None,  # noqa: A002
    step: str | None = None,
    actions: list[str] | None = None,
    nexts: list[str] | None = None,
    has_time: bool | None = None,
    has_part_a: bool | None = None,
    has_part_b: bool | None = None,
    age: int | None = None,
    has_disability: bool | None = None,
    eligible: bool | None = None,
    dnc: bool | None = None,
    abuse: bool | None = None,
    side_topic: bool | None = None,
    message_any: list[str] | None = None,
) -> dict[str, Any]:
    e: dict[str, Any] = {}
    if action is not None:
        e["action"] = action
    if actions is not None:
        e["actions"] = actions
    if next is not None:
        e["next"] = next
    if nexts is not None:
        e["nexts"] = nexts
    if step is not None:
        e["step"] = step
    if has_time is not None:
        e["has_time"] = has_time
    if has_part_a is not None:
        e["has_part_a"] = has_part_a
    if has_part_b is not None:
        e["has_part_b"] = has_part_b
    if age is not None:
        e["age"] = age
    if has_disability is not None:
        e["has_disability"] = has_disability
    if eligible is not None:
        e["eligible"] = eligible
    if dnc is not None:
        e["dnc"] = dnc
    if abuse is not None:
        e["abuse"] = abuse
    if side_topic is not None:
        e["side_topic"] = side_topic
    if message_any is not None:
        e["message_any"] = message_any
    return e


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "happy_65_plus",
        "description": "Happy path age >= 65 → transfer",
        "turns": [
            {
                "user": "",
                "expect": _expect(
                    action="continue",
                    nexts=["intro", "await_time", "ask_parts"],
                    message_any=["minute", "minutes", "time", "Sarah", "Medicare"],
                ),
            },
            {
                "user": "Yes, I have a few minutes.",
                "expect": _expect(
                    action="continue",
                    next="ask_parts",
                    has_time=True,
                    message_any=["Part A", "Part B", "Medicare"],
                ),
            },
            {
                "user": "Yes, I have Part A and Part B.",
                "expect": _expect(
                    action="continue",
                    next="ask_age",
                    has_part_a=True,
                    has_part_b=True,
                    message_any=["age", "old", "65"],
                ),
            },
            {
                "user": "I'm 72.",
                "expect": _expect(
                    action="transfer",
                    next="done",
                    age=72,
                    eligible=True,
                    message_any=["transfer", "connect", "licensed", "specialist", "agent"],
                ),
            },
        ],
    },
    {
        "id": "happy_under65_disability",
        "description": "Under 65 with disability → transfer",
        "turns": [
            {
                "user": "",
                "expect": _expect(action="continue", nexts=["intro", "await_time", "ask_parts"]),
            },
            {
                "user": "Sure, go ahead.",
                "expect": _expect(action="continue", next="ask_parts", has_time=True),
            },
            {
                "user": "I have both Part A and B.",
                "expect": _expect(
                    action="continue",
                    next="ask_age",
                    has_part_a=True,
                    has_part_b=True,
                ),
            },
            {
                "user": "I'm 58 years old.",
                "expect": _expect(
                    action="continue",
                    next="ask_disability",
                    age=58,
                    message_any=["disability", "disabled", "SSDI", "Social Security"],
                ),
            },
            {
                "user": "Yes, I receive disability benefits.",
                "expect": _expect(
                    action="transfer",
                    next="done",
                    has_disability=True,
                    eligible=True,
                    message_any=["transfer", "connect", "licensed", "specialist", "agent"],
                ),
            },
        ],
    },
    {
        "id": "under65_no_disability",
        "description": "Under 65 without disability → close_ineligible",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "Yes I can talk.",
                "expect": _expect(action="continue", next="ask_parts", has_time=True),
            },
            {
                "user": "Yes Part A and Part B.",
                "expect": _expect(action="continue", next="ask_age"),
            },
            {
                "user": "I'm 45.",
                "expect": _expect(action="continue", next="ask_disability", age=45),
            },
            {
                "user": "No, I don't get disability.",
                "expect": _expect(
                    action="close_ineligible",
                    next="done",
                    has_disability=False,
                    eligible=False,
                    message_any=["thank", "eligible", "not", "sorry", "appreciate"],
                ),
            },
        ],
    },
    {
        "id": "no_time",
        "description": "Caller has no time → close or briefly offer callback (ask-again OK)",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "No, I don't have time right now.",
                "expect": _expect(
                    actions=["close_no_time", "continue"],
                    nexts=["done", "await_time", "ask_parts", "close"],
                    message_any=[
                        "thank",
                        "later",
                        "sorry",
                        "appreciate",
                        "bye",
                        "goodbye",
                        "understand",
                        "call back",
                        "another time",
                        "moments",
                        "convenient",
                        "schedule",
                        "question",
                    ],
                ),
            },
        ],
    },
    {
        "id": "no_parts",
        "description": "No Part A/B → close OR confirm/ask again (ask-again OK)",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "Yes, I have a few minutes.",
                "expect": _expect(action="continue", next="ask_parts", has_time=True),
            },
            {
                "user": "No, I don't have Medicare Part A or B.",
                "expect": _expect(
                    actions=["close_no_parts", "continue"],
                    nexts=["done", "ask_parts"],
                    message_any=[
                        "thank",
                        "sorry",
                        "eligible",
                        "appreciate",
                        "Part",
                        "Medicare",
                        "confirm",
                        "have",
                    ],
                ),
            },
        ],
    },
    {
        "id": "side_topic_then_continue",
        "description": "Side topic mid-flow then resume to transfer",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "Yes go ahead.",
                "expect": _expect(action="continue", next="ask_parts"),
            },
            {
                "user": "Yes I have Part A and B.",
                "expect": _expect(action="continue", next="ask_age"),
            },
            {
                "user": "My dog is barking loudly.",
                "expect": _expect(
                    action="continue",
                    next="ask_age",
                    message_any=["age", "old", "65"],
                ),
            },
            {
                "user": "I'm 68.",
                "expect": _expect(action="transfer", next="done", age=68, eligible=True),
            },
        ],
    },
    {
        "id": "vague_then_clarify",
        "description": "Vague answer stays on step, then continues",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "Sure.",
                "expect": _expect(action="continue", next="ask_parts"),
            },
            {
                "user": "I'm not sure.",
                "expect": _expect(
                    action="continue",
                    nexts=["ask_parts"],
                    message_any=[
                        "Part A",
                        "Part B",
                        "Medicare",
                        "clarify",
                        "confirm",
                        "have",
                        "sure",
                        "both",
                    ],
                ),
            },
            {
                "user": "Yes, both Part A and Part B.",
                "expect": _expect(action="continue", next="ask_age"),
            },
            {
                "user": "71",
                "expect": _expect(action="transfer", next="done", eligible=True),
            },
        ],
    },
    {
        "id": "dnc_mid_flow",
        "description": "DNC request mid-flow ends call",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "Yes I can talk.",
                "expect": _expect(action="continue", next="ask_parts"),
            },
            {
                "user": "Stop calling me. Remove me from your list.",
                "expect": _expect(
                    action="dnc",
                    next="done",
                    dnc=True,
                    message_any=["stop", "list", "contact", "sorry", "remove", "call", "noted"],
                ),
            },
        ],
    },
    {
        "id": "abuse_end",
        "description": "Abusive caller → end_abuse",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": (
                    "Shut up you damn scam artist! If you call again I'll "
                    "report you to the FBI. Stop harassing me!"
                ),
                "expect": _expect(
                    action="end_abuse",
                    next="done",
                    abuse=True,
                    message_any=[
                        "sorry",
                        "end",
                        "goodbye",
                        "bye",
                        "hang",
                        "disturb",
                        "understand",
                        "upset",
                        "call",
                    ],
                ),
            },
        ],
    },
    {
        "id": "partial_parts_clarify",
        "description": "Only Part A — clarify before advancing",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "Yes, go ahead.",
                "expect": _expect(action="continue", next="ask_parts"),
            },
            {
                "user": "I only have Part A.",
                "expect": _expect(
                    actions=["continue", "close_no_parts"],
                    nexts=["ask_parts", "done"],
                    message_any=["Part B", "both", "Part A", "thank", "eligible"],
                ),
            },
        ],
    },
    {
        "id": "early_transfer_request",
        "description": "Asks for human before eligible — stay on flow then transfer",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "Yes I have a minute.",
                "expect": _expect(action="continue", next="ask_parts"),
            },
            {
                "user": "Just transfer me to an agent already.",
                "expect": _expect(
                    action="continue",
                    next="ask_parts",
                    message_any=[
                        "Part A",
                        "Part B",
                        "Medicare",
                        "first",
                        "quick",
                        "before",
                        "few",
                        "qualify",
                        "question",
                    ],
                ),
            },
            {
                "user": "Fine, I have Part A and B.",
                "expect": _expect(action="continue", next="ask_age"),
            },
            {
                "user": "I'm 66.",
                "expect": _expect(action="transfer", next="done", age=66, eligible=True),
            },
        ],
    },
    {
        "id": "not_interested_as_no_time",
        "description": "Not interested treated as no time / close",
        "turns": [
            {"user": "", "expect": _expect(action="continue")},
            {
                "user": "Not interested. Call me never.",
                "expect": _expect(
                    actions=["close_no_time", "dnc"],
                    next="done",
                ),
            },
        ],
    },
]


def get_scenario(scenario_id: str) -> dict[str, Any]:
    for s in SCENARIOS:
        if s["id"] == scenario_id:
            return s
    raise KeyError(f"Unknown scenario: {scenario_id}")


def stress_turn_contexts() -> list[dict[str, Any]]:
    """Single-turn stress samples: mid-flow user + prior state."""
    return [
        {
            "id": "open",
            "prior_state": {
                "step": "intro",
                "has_time": None,
                "has_part_a": None,
                "has_part_b": None,
                "age": None,
                "has_disability": None,
                "eligible": None,
                "flags": {"dnc": False, "abuse": False, "side_topic": False},
            },
            "user": "",
            "is_opening": True,
        },
        {
            "id": "yes_time",
            "prior_state": {
                "step": "await_time",
                "has_time": None,
                "has_part_a": None,
                "has_part_b": None,
                "age": None,
                "has_disability": None,
                "eligible": None,
                "flags": {"dnc": False, "abuse": False, "side_topic": False},
            },
            "user": "Yes I have a few minutes",
            "is_opening": False,
        },
        {
            "id": "has_parts",
            "prior_state": {
                "step": "ask_parts",
                "has_time": True,
                "has_part_a": None,
                "has_part_b": None,
                "age": None,
                "has_disability": None,
                "eligible": None,
                "flags": {"dnc": False, "abuse": False, "side_topic": False},
            },
            "user": "Yes I have Part A and Part B",
            "is_opening": False,
        },
        {
            "id": "age_72",
            "prior_state": {
                "step": "ask_age",
                "has_time": True,
                "has_part_a": True,
                "has_part_b": True,
                "age": None,
                "has_disability": None,
                "eligible": None,
                "flags": {"dnc": False, "abuse": False, "side_topic": False},
            },
            "user": "I'm 72",
            "is_opening": False,
        },
        {
            "id": "disability_yes",
            "prior_state": {
                "step": "ask_disability",
                "has_time": True,
                "has_part_a": True,
                "has_part_b": True,
                "age": 58,
                "has_disability": None,
                "eligible": None,
                "flags": {"dnc": False, "abuse": False, "side_topic": False},
            },
            "user": "Yes I receive disability benefits",
            "is_opening": False,
        },
        {
            "id": "dnc",
            "prior_state": {
                "step": "ask_parts",
                "has_time": True,
                "has_part_a": None,
                "has_part_b": None,
                "age": None,
                "has_disability": None,
                "eligible": None,
                "flags": {"dnc": False, "abuse": False, "side_topic": False},
            },
            "user": "Remove me from your list. Do not call again.",
            "is_opening": False,
        },
        {
            "id": "side_topic",
            "prior_state": {
                "step": "ask_age",
                "has_time": True,
                "has_part_a": True,
                "has_part_b": True,
                "age": None,
                "has_disability": None,
                "eligible": None,
                "flags": {"dnc": False, "abuse": False, "side_topic": False},
            },
            "user": "The weather is really hot today",
            "is_opening": False,
        },
    ]


def session_scripts_for_stress() -> list[dict[str, Any]]:
    """Shorter multi-turn scripts for concurrent session stress."""
    preferred = [
        "happy_65_plus",
        "happy_under65_disability",
        "under65_no_disability",
        "no_time",
        "no_parts",
        "dnc_mid_flow",
    ]
    by_id = {s["id"]: s for s in SCENARIOS}
    return [by_id[i] for i in preferred if i in by_id]
