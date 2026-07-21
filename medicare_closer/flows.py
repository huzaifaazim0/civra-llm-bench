"""Scripted multi-turn Medicare closer conversation scenarios."""

from __future__ import annotations

from typing import Any

from schema import empty_state


def _expect(
    *,
    action: str | None = None,
    next: str | None = None,  # noqa: A002
    step: str | None = None,
    actions: list[str] | None = None,
    nexts: list[str] | None = None,
    decision_maker: bool | None = None,
    soa_agreed: bool | None = None,
    voice_signed: bool | None = None,
    other_coverage: str | None = None,
    selected_plan_id: str | None = None,
    current_plan: str | None = None,
    medicaid_dual: bool | None = None,
    dnc: bool | None = None,
    abuse: bool | None = None,
    side_topic: bool | None = None,
    conditions_any: list[str] | None = None,
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
    if decision_maker is not None:
        e["decision_maker"] = decision_maker
    if soa_agreed is not None:
        e["soa_agreed"] = soa_agreed
    if voice_signed is not None:
        e["voice_signed"] = voice_signed
    if other_coverage is not None:
        e["other_coverage"] = other_coverage
    if selected_plan_id is not None:
        e["selected_plan_id"] = selected_plan_id
    if current_plan is not None:
        e["current_plan"] = current_plan
    if medicaid_dual is not None:
        e["medicaid_dual"] = medicaid_dual
    if dnc is not None:
        e["dnc"] = dnc
    if abuse is not None:
        e["abuse"] = abuse
    if side_topic is not None:
        e["side_topic"] = side_topic
    if conditions_any is not None:
        e["conditions_any"] = conditions_any
    if message_any is not None:
        e["message_any"] = message_any
    return e


# Soft continue: any qualification / compliance step
_QUAL_NEXTS = [
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
]

_ENROLL_NEXTS = [
    "plan_review",
    "dual_attestation",
    "plan_confirm",
    "address",
    "enrollment_readback",
    "voice_signature",
    "close_success",
]


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "happy_enroll_otc",
        "description": "Happy path — qualify + enroll otc_zero with voice signature",
        "turns": [
            {
                "user": "",
                "expect": _expect(
                    action="continue",
                    nexts=["intro", "disclaimers", "soa", "ask_decision_maker"],
                    message_any=["licensed", "plan", "2026", "agent", "review", "benefit"],
                ),
            },
            {
                "user": "Yes, sounds good.",
                "expect": _expect(
                    action="continue",
                    nexts=["disclaimers", "soa", "ask_decision_maker"],
                    message_any=["record", "Medicare", "appointment", "agree", "plan", "Scope", "quality"],
                ),
            },
            {
                "user": "Yes, I agree to continue.",
                "expect": _expect(
                    action="continue",
                    nexts=["ask_decision_maker", "ask_callback", "ask_satisfaction", "soa"],
                    soa_agreed=True,
                ),
            },
            {
                "user": "Yes, I make my own healthcare decisions.",
                "expect": _expect(
                    action="continue",
                    decision_maker=True,
                    nexts=[
                        "ask_callback",
                        "verify_zip",
                        "verify_dob",
                        "medicare_permission",
                        "ask_satisfaction",
                        "ask_conditions",
                    ],
                ),
            },
            {
                "user": "Yes, you can call me back at this number.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "Humana has been fine.",
                "expect": _expect(
                    action="continue",
                    nexts=[
                        "ask_conditions",
                        "ask_doctor",
                        "ask_meds",
                        "ask_priorities",
                        "ask_satisfaction",
                    ],
                ),
            },
            {
                "user": "Yeah, I have diabetes.",
                "expect": _expect(
                    action="continue",
                    nexts=["ask_doctor", "ask_meds", "ask_conditions", "ask_priorities"],
                    conditions_any=["diabet"],
                ),
            },
            {
                "user": "I don't go to the doctor very often.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "Just one blood pressure medication.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "I want something that doesn't cost too much.",
                "expect": _expect(
                    action="continue",
                    nexts=[
                        "ask_living",
                        "ask_other_coverage",
                        "plan_review",
                        "ask_priorities",
                    ],
                ),
            },
            {
                "user": "No, I live at home. No other coverage through work or VA.",
                "expect": _expect(
                    action="continue",
                    nexts=["plan_review", "ask_living", "ask_other_coverage", "plan_confirm"],
                ),
            },
            {
                "user": "That OTC plan sounds good — let's do it.",
                "expect": _expect(
                    action="continue",
                    nexts=_ENROLL_NEXTS,
                    selected_plan_id="otc_zero",
                ),
            },
            {
                "user": "123 Main Street, Springfield.",
                "expect": _expect(
                    action="continue",
                    nexts=["address", "enrollment_readback", "voice_signature", "plan_confirm"],
                ),
            },
            {
                "user": "Yes, I agree to all of that.",
                "expect": _expect(
                    action="continue",
                    nexts=["enrollment_readback", "voice_signature", "close_success"],
                ),
            },
            {
                "user": "Pat Smith. January 15, 1955. Today is July 21, 2026. I agree.",
                "expect": _expect(
                    action="enroll_success",
                    next="done",
                    selected_plan_id="otc_zero",
                    voice_signed=True,
                    soa_agreed=True,
                    message_any=["set", "effective", "card", "thank", "plan", "mail", "all set"],
                ),
            },
        ],
    },
    {
        "id": "ssn_medicaid_fallback",
        "description": "Lost Medicare card / Medicaid hesitation → dual food plan path",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Okay, go ahead.",
                "expect": _expect(action="continue", nexts=["disclaimers", "soa", "ask_decision_maker"]),
            },
            {
                "user": "Yes I agree.",
                "expect": _expect(action="continue", soa_agreed=True, nexts=_QUAL_NEXTS),
            },
            {
                "user": "Yes I make my own decisions. Humana is okay but I can't find my Medicare card.",
                "expect": _expect(
                    action="continue",
                    decision_maker=True,
                    nexts=_QUAL_NEXTS,
                    message_any=["okay", "pulled", "information", "card", "Medicaid", "look", "system", "already"],
                ),
            },
            {
                "user": "I don't want to give out my Social Security number.",
                "expect": _expect(
                    action="continue",
                    nexts=_QUAL_NEXTS,
                    message_any=["understand", "recorded", "Medicaid", "protect", "wait", "card", "Social"],
                ),
            },
            {
                "user": "Okay fine — I found my Medicaid card. Yes I'm dual eligible.",
                "expect": _expect(
                    action="continue",
                    nexts=_QUAL_NEXTS + _ENROLL_NEXTS,
                    medicaid_dual=True,
                ),
            },
            {
                "user": "I've never gotten cash back on my plans.",
                "expect": _expect(
                    action="continue",
                    nexts=_QUAL_NEXTS + _ENROLL_NEXTS,
                    message_any=["Medicaid", "food", "dental", "giveback", "Part B", "premium", "card"],
                ),
            },
            {
                "user": "Diabetes. The food card plan sounds better — let's enroll.",
                "expect": _expect(
                    action="continue",
                    nexts=_ENROLL_NEXTS + ["ask_conditions", "ask_doctor", "dual_attestation"],
                    selected_plan_id="dual_food_snp",
                ),
            },
            {
                "user": "Dr. Lee, 555-0100. I've seen him this year. I attest to diabetes.",
                "expect": _expect(action="continue", nexts=_ENROLL_NEXTS),
            },
            {
                "user": "456 Oak Ave. Yes I agree to enroll. Mary Jones, March 3 1948, July 21 2026, I agree.",
                "expect": _expect(
                    actions=["enroll_success", "continue"],
                    nexts=["done", "voice_signature", "enrollment_readback", "address", "close_success"],
                    selected_plan_id="dual_food_snp",
                ),
            },
        ],
    },
    {
        "id": "angry_deescalate_continue",
        "description": "Frustrated caller — de-escalate then continue qualification",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": (
                    "I'm tired of all these calls. Every day someone's calling me about "
                    "Medicare. I don't know who you people are."
                ),
                "expect": _expect(
                    action="continue",
                    nexts=["intro", "disclaimers", "soa", "ask_decision_maker", "ask_callback"],
                    message_any=["understand", "sorry", "frustrat", "licensed", "pressure", "list", "hear"],
                ),
            },
            {
                "user": "I guess you can tell me what you got.",
                "expect": _expect(
                    action="continue",
                    nexts=["disclaimers", "soa", "ask_decision_maker", "ask_satisfaction"],
                ),
            },
            {
                "user": "Yes I agree, and yes I make my own decisions. Aetna is fine.",
                "expect": _expect(
                    action="continue",
                    decision_maker=True,
                    nexts=_QUAL_NEXTS,
                ),
            },
        ],
    },
    {
        "id": "employer_conflict",
        "description": "Employer coverage → close_employer_conflict",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Sure.",
                "expect": _expect(action="continue", nexts=["disclaimers", "soa", "ask_decision_maker"]),
            },
            {
                "user": "Yes I agree to the appointment.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "Yes I make my own decisions.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "My plan is okay. No diabetes. Rarely see a doctor. No meds. Just low cost.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "I live at home. Yeah, I still have insurance through my job — retired but they kept me on.",
                "expect": _expect(
                    action="close_employer_conflict",
                    next="done",
                    other_coverage="employer",
                    message_any=["employer", "job", "benefits", "affect", "disrupt", "recommend", "coverage"],
                ),
            },
        ],
    },
    {
        "id": "dnc_immediate",
        "description": "Immediate DNC / not interested",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "I'm not interested. Stop calling me.",
                "expect": _expect(
                    action="dnc",
                    next="done",
                    dnc=True,
                    message_any=["remove", "list", "888", "Do Not Call", "stop", "call"],
                ),
            },
        ],
    },
    {
        "id": "no_better_plan",
        "description": "Review finds current plan optimal",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Yes let's review.",
                "expect": _expect(action="continue", nexts=["disclaimers", "soa", "ask_decision_maker"]),
            },
            {
                "user": "I agree. Yes I make my own decisions. I love my current Humana plan — dental, OTC, everything.",
                "expect": _expect(action="continue", decision_maker=True, nexts=_QUAL_NEXTS),
            },
            {
                "user": "No chronic conditions, no meds, no other coverage. I'm happy — is there anything better?",
                "expect": _expect(
                    actions=["close_optimal_current", "continue"],
                    nexts=["done", "plan_review", "ask_other_coverage", "ask_living", "ask_priorities"],
                ),
            },
            {
                "user": "Okay, if nothing is better I'll stay put.",
                "expect": _expect(
                    action="close_optimal_current",
                    next="done",
                    message_any=["current", "best", "still", "option", "file", "good", "stay"],
                ),
            },
        ],
    },
    {
        "id": "not_decision_maker",
        "description": "Caller does not make own healthcare decisions",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Okay.",
                "expect": _expect(action="continue", nexts=["disclaimers", "soa", "ask_decision_maker"]),
            },
            {
                "user": "Yes I agree to continue.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "No, my daughter handles all my medical and insurance decisions.",
                "expect": _expect(
                    actions=["close_not_decision_maker", "callback", "continue"],
                    nexts=["done", "ask_decision_maker", "ask_callback"],
                    decision_maker=False,
                    message_any=["daughter", "speak", "decision", "call", "authorized", "someone", "help"],
                ),
            },
        ],
    },
    {
        "id": "callback_busy",
        "description": "Not a good time → schedule callback",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "This isn't a good time. Call me back later.",
                "expect": _expect(
                    actions=["callback", "continue"],
                    nexts=["done", "ask_callback", "intro", "disclaimers"],
                    message_any=["day", "time", "call", "back", "schedule", "when", "convenient"],
                ),
            },
            {
                "user": "Thursday at 2pm works. Same number.",
                "expect": _expect(
                    action="callback",
                    next="done",
                    message_any=["Thursday", "2", "call", "back", "number", "talk"],
                ),
            },
        ],
    },
    {
        "id": "side_topic_tangent",
        "description": "Long tangent mid-flow → ack and resume same question",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Yes go ahead.",
                "expect": _expect(action="continue", nexts=["disclaimers", "soa", "ask_decision_maker"]),
            },
            {
                "user": "Yes I agree, and yes I make my own decisions.",
                "expect": _expect(action="continue", decision_maker=True, nexts=_QUAL_NEXTS),
            },
            {
                "user": (
                    "Before I answer about my plan — let me tell you about my grandson's baseball "
                    "tournament last weekend, we drove six hours and the hotel lost our reservation..."
                ),
                "expect": _expect(
                    action="continue",
                    nexts=[
                        "ask_satisfaction",
                        "ask_callback",
                        "ask_conditions",
                        "medicare_permission",
                        "verify_zip",
                        "ask_doctor",
                    ],
                    message_any=[
                        "appreciate",
                        "sharing",
                        "plan",
                        "doctor",
                        "liking",
                        "Humana",
                        "Aetna",
                        "coverage",
                        "question",
                    ],
                ),
            },
            {
                "user": "Sorry — Humana's been okay.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
        ],
    },
    {
        "id": "rural_network_concern",
        "description": "Rural 'no doctors' concern → network-focused pitch",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Fine. Yes I agree. I make my own decisions.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "My plan is okay but there's no doctors up here in the country.",
                "expect": _expect(
                    action="continue",
                    nexts=_QUAL_NEXTS + _ENROLL_NEXTS,
                    message_any=["network", "doctor", "near", "address", "home", "town", "look", "available", "PPO"],
                ),
            },
            {
                "user": "If you can find something with doctors near me and low cost, I'll listen.",
                "expect": _expect(
                    action="continue",
                    nexts=_QUAL_NEXTS + _ENROLL_NEXTS,
                ),
            },
        ],
    },
    {
        "id": "giveback_vs_medicaid",
        "description": "Never got cash back — explain Medicaid, pitch dual/OTC",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Yes. I agree. I decide for myself. I have Medicaid too.",
                "expect": _expect(
                    action="continue",
                    nexts=_QUAL_NEXTS,
                    medicaid_dual=True,
                ),
            },
            {
                "user": "I've never gotten cash back. Why not?",
                "expect": _expect(
                    action="continue",
                    nexts=_QUAL_NEXTS + _ENROLL_NEXTS,
                    message_any=["Medicaid", "Part B", "premium", "food", "dental", "giveback", "cash"],
                ),
            },
            {
                "user": "Okay, show me the food card option then.",
                "expect": _expect(
                    action="continue",
                    nexts=_ENROLL_NEXTS + ["ask_conditions", "ask_doctor", "ask_meds", "plan_review"],
                    selected_plan_id="dual_food_snp",
                ),
            },
        ],
    },
    {
        "id": "dual_snp_attestation",
        "description": "Dual SNP path with chronic attestation + PCP phone",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Yes. Agree. I make decisions. I'm dual eligible with diabetes.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS, medicaid_dual=True),
            },
            {
                "user": "No employer coverage. I want the food and utility benefits.",
                "expect": _expect(
                    action="continue",
                    nexts=_ENROLL_NEXTS + ["ask_doctor", "ask_meds", "ask_priorities", "dual_attestation", "plan_review"],
                    selected_plan_id="dual_food_snp",
                ),
            },
            {
                "user": "I attest I have diabetes. My primary doctor is Dr. Patel at 555-2222, seen him last month.",
                "expect": _expect(
                    action="continue",
                    nexts=_ENROLL_NEXTS,
                    message_any=["address", "confirm", "enroll", "benefit", "agree", "doctor", "attesta", "plan"],
                ),
            },
        ],
    },
    {
        "id": "va_tricare_ok",
        "description": "VA coverage — coordinate and proceed carefully",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Yes. I agree. I make my own decisions.",
                "expect": _expect(action="continue", decision_maker=True, nexts=_QUAL_NEXTS),
            },
            {
                "user": "I also have VA benefits.",
                "expect": _expect(
                    action="continue",
                    nexts=_QUAL_NEXTS + _ENROLL_NEXTS,
                    other_coverage="va",
                    message_any=["VA", "separately", "coordinate", "Medicare", "still", "work"],
                ),
            },
            {
                "user": "Okay, as long as they work together I'm fine to look at options.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS + _ENROLL_NEXTS),
            },
        ],
    },
    {
        "id": "abuse_hostile",
        "description": "Remains hostile after de-escalate → end_abuse or dnc",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Why do you keep harassing me? These calls are ridiculous.",
                "expect": _expect(
                    actions=["continue", "dnc", "end_abuse"],
                    nexts=["done", "intro", "disclaimers", "soa", "ask_decision_maker", "ask_callback"],
                ),
            },
            {
                "user": (
                    "Shut up. If you call again I'll report you. Stop harassing me you scam artist!"
                ),
                "expect": _expect(
                    actions=["end_abuse", "dnc"],
                    next="done",
                    message_any=["understand", "won't", "call", "list", "goodbye", "day", "note", "preference"],
                ),
            },
        ],
    },
    {
        "id": "skip_optional_verify",
        "description": "Happy path skipping zip/dob/callback — still reaches plan review",
        "turns": [
            {"user": "", "expect": _expect(action="continue", nexts=["intro", "disclaimers", "soa"])},
            {
                "user": "Yes sounds good. I agree to recorded call and SOA.",
                "expect": _expect(action="continue", nexts=_QUAL_NEXTS),
            },
            {
                "user": "I make my own decisions. Current plan is United. No diabetes. Few meds. Low cost. Live at home. No other coverage.",
                "expect": _expect(
                    action="continue",
                    decision_maker=True,
                    nexts=_QUAL_NEXTS + _ENROLL_NEXTS,
                ),
            },
            {
                "user": "Tell me about the zero premium OTC option.",
                "expect": _expect(
                    action="continue",
                    nexts=_ENROLL_NEXTS + ["ask_priorities", "ask_meds"],
                    selected_plan_id="otc_zero",
                    message_any=["44", "OTC", "over-the-counter", "premium", "Walmart", "Walgreens", "zero", "$0"],
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
    base = empty_state("ask_satisfaction")
    base.update(
        {
            "decision_maker": True,
            "soa_agreed": True,
            "current_plan": "Humana",
        }
    )
    return [
        {
            "id": "open",
            "prior_state": empty_state("intro"),
            "user": "",
            "is_opening": True,
        },
        {
            "id": "soa_yes",
            "prior_state": {
                **empty_state("soa"),
                "caller_name": "Pat",
            },
            "user": "Yes, I agree to continue the appointment.",
            "is_opening": False,
        },
        {
            "id": "decision_yes",
            "prior_state": {
                **empty_state("ask_decision_maker"),
                "soa_agreed": True,
            },
            "user": "Yes, I make all of my own healthcare decisions.",
            "is_opening": False,
        },
        {
            "id": "diabetes",
            "prior_state": {
                **base,
                "step": "ask_conditions",
            },
            "user": "Yes, I have diabetes.",
            "is_opening": False,
        },
        {
            "id": "employer",
            "prior_state": {
                **base,
                "step": "ask_other_coverage",
                "nursing_home": False,
            },
            "user": "I still have insurance through my employer.",
            "is_opening": False,
        },
        {
            "id": "dnc",
            "prior_state": {
                **empty_state("ask_satisfaction"),
                "soa_agreed": True,
                "decision_maker": True,
            },
            "user": "Stop calling me. Remove me from your list.",
            "is_opening": False,
        },
        {
            "id": "side_topic",
            "prior_state": {
                **base,
                "step": "ask_conditions",
            },
            "user": "Anyway my dog is barking and the weather is crazy today.",
            "is_opening": False,
        },
        {
            "id": "voice_sig",
            "prior_state": {
                **empty_state("voice_signature"),
                "decision_maker": True,
                "soa_agreed": True,
                "selected_plan_id": "otc_zero",
                "other_coverage": "none",
                "effective_date": "January 1, 2026",
            },
            "user": "Pat Smith. January 15, 1955. July 21, 2026. I agree.",
            "is_opening": False,
        },
    ]


def session_scripts_for_stress() -> list[dict[str, Any]]:
    """Shorter multi-turn scripts for concurrent session stress."""
    preferred = [
        "dnc_immediate",
        "callback_busy",
        "employer_conflict",
        "not_decision_maker",
        "angry_deescalate_continue",
        "abuse_hostile",
    ]
    by_id = {s["id"]: s for s in SCENARIOS}
    return [by_id[i] for i in preferred if i in by_id]
