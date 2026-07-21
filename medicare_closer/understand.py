"""LLM-based caller-reply understanding for the Medicare closer.

The LLM tells the controller the status of the CURRENT step:
  pass | fail | in_progress | side_chat | clarify

Side chats can take multiple turns. The controller keeps the same step
anchored until the LLM reports pass (or a terminal fail/interrupt).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from plans import PLAN_IDS

StepStatus = Literal["pass", "fail", "in_progress", "side_chat", "clarify"]

UNDERSTAND_SYSTEM = """You are the turn-judge for a Medicare closer phone agent.
You do NOT speak to the caller. Output ONLY JSON for the controller.

The controller is stuck on ONE current script step until you say that step is done.

## step_status (required — this is what the controller trusts)

- "pass" — The current step is COMPLETE. Enough clear info to move to the next script step.
- "fail" — The step failed in a terminal way for this call (e.g. not the decision-maker, refuses SOA, rejects enrollment permanently). Use with interrupt or facts that explain why.
- "in_progress" — They engaged but the step is NOT done yet (partial answer). Stay on this step; ask the follow-up.
- "side_chat" — They went off-topic, asked a side question, told a story, or need rapport. Stay on the SAME step. Answer/ack them, then gently steer back. Side chat may take MULTIPLE turns — that is OK. Do NOT pass until they actually answer the step.
- "clarify" — Unclear, garbled, silent, or ambiguous. Stay; re-ask simply with an example. Never coach "I didn't quite catch that".

## Multi-turn side chat (important)

If side_chat_active is true, you are MID side-chat on the anchored step.
- Keep step_status="side_chat" until they give a real answer to the anchored question.
- When they finally answer the anchored question clearly → step_status="pass".
- Do NOT advance just because the side topic ended politely — only when the step question is answered.

## Other fields

- kind: answer|question|objection|unclear|gibberish|empty|tangent|interrupt
- interrupt: null|dnc|callback|abuse|hostile
- facts: only clearly stated facts (never invent). Asking "what is diabetes?" must NOT set conditions=diabetes.
- speech_hint: 1–3 coaching sentences for the speaking agent (what to say THIS turn).
- emotion: warm|empathetic|helpful|patient|understanding|celebratory
- resume_hint: if side_chat/clarify/in_progress, how to bring them back to the step question.

## Examples

Current step ask_conditions, caller: "what is diabetes?"
→ step_status=side_chat, kind=question, facts={}, speech_hint=explain diabetes briefly then re-ask if THEY have it.

Same step later, caller: "oh ok no I don't have that"
→ step_status=pass, facts.conditions=["none"]

Current step ask_living, caller: "where's the nearest nursing home?"
→ step_status=side_chat (not living in one), explain you don't look up facilities; ask if they live at home or in a facility.

Current step ask_meds, caller: "suuuuure wait also my grandson..."
→ if they didn't answer meds: side_chat or in_progress; stay until meds answered.
"""


@dataclass
class Understanding:
    step_status: StepStatus = "clarify"
    kind: str = "unclear"
    answered_current: bool = False
    advance: bool = False  # derived from step_status==pass (or terminal fail)
    interrupt: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    speech_hint: str = ""
    resume_hint: str = ""
    emotion: str = "warm"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def stay(self) -> bool:
        return self.step_status in ("in_progress", "side_chat", "clarify")


def build_understand_user(
    *,
    step: str,
    step_question: str,
    caller_text: str,
    state: dict[str, Any],
    side_chat_active: bool = False,
    side_chat_depth: int = 0,
    anchor_step: str | None = None,
) -> str:
    known = {
        "soa_agreed": state.get("soa_agreed"),
        "decision_maker": state.get("decision_maker"),
        "callback_ok": state.get("callback_ok"),
        "current_plan": state.get("current_plan"),
        "conditions": state.get("conditions"),
        "doctor": state.get("doctor"),
        "meds": state.get("meds"),
        "priorities": state.get("priorities"),
        "nursing_home": state.get("nursing_home"),
        "other_coverage": state.get("other_coverage"),
        "selected_plan_id": state.get("selected_plan_id"),
        "plan_satisfaction": state.get("plan_satisfaction"),
        "flags": state.get("flags"),
    }
    side_block = (
        f"side_chat_active: {str(side_chat_active).lower()}\n"
        f"side_chat_depth (turns already spent off-step): {side_chat_depth}\n"
        f"anchor_step (must complete before advancing): {anchor_step or step}\n"
    )
    return (
        f"Current step: {step}\n"
        f"What this step needs: {step_question}\n"
        f"{side_block}"
        f"Already known state (JSON): {json.dumps(known, ensure_ascii=False)}\n"
        f'Caller just said: "{caller_text}"\n\n'
        "Return ONLY JSON:\n"
        "{\n"
        '  "step_status": "pass|fail|in_progress|side_chat|clarify",\n'
        '  "kind": "answer|question|objection|unclear|gibberish|empty|tangent|interrupt",\n'
        '  "interrupt": null,\n'
        '  "facts": {},\n'
        '  "speech_hint": "...",\n'
        '  "resume_hint": "...",\n'
        '  "emotion": "warm"\n'
        "}\n"
        "facts may include: decision_maker, callback_ok, soa_agreed, current_plan, "
        "plan_satisfaction, conditions, doctor, meds, priorities, nursing_home, "
        "other_coverage, selected_plan_id (giveback_ppo|otc_zero|dual_food_snp), "
        "address, caller_name, voice_signed, medicaid_dual.\n"
        "Only pass when the CURRENT step question is truly satisfied."
    )


def parse_understanding(text: str) -> Understanding:
    obj = _extract_json(text)
    if not obj:
        return Understanding(
            step_status="clarify",
            kind="unclear",
            answered_current=False,
            advance=False,
            speech_hint=(
                "Unsure what they meant. Acknowledge briefly and re-ask the current "
                "step with one simple example answer."
            ),
            resume_hint="Return to the current step question.",
            emotion="patient",
        )

    status = str(obj.get("step_status") or "").lower().strip()
    # Back-compat with older advance/answered_current fields
    if status not in ("pass", "fail", "in_progress", "side_chat", "clarify"):
        if obj.get("advance") is True or obj.get("answered_current") is True:
            status = "pass"
        elif str(obj.get("kind") or "") in ("question", "tangent"):
            status = "side_chat"
        elif str(obj.get("kind") or "") in ("empty", "gibberish", "unclear"):
            status = "clarify"
        elif str(obj.get("kind") or "") == "objection":
            status = "in_progress"
        else:
            status = "clarify"

    kind = str(obj.get("kind") or "unclear").lower().strip()
    if kind not in {
        "answer",
        "question",
        "objection",
        "unclear",
        "gibberish",
        "empty",
        "tangent",
        "interrupt",
    }:
        kind = "unclear"

    interrupt = obj.get("interrupt")
    if interrupt in ("", "null", "none", None):
        interrupt = None
    elif isinstance(interrupt, str):
        interrupt = interrupt.lower().strip()
        if interrupt not in ("dnc", "callback", "abuse", "hostile"):
            interrupt = None

    facts = _clean_facts(obj.get("facts") if isinstance(obj.get("facts"), dict) else {})

    if interrupt in ("dnc", "callback", "abuse"):
        status = "fail"
    if kind in ("empty", "gibberish") and status == "pass":
        status = "clarify"
    if kind in ("question", "tangent") and status == "pass":
        # Don't allow pass on pure side talk unless model was explicit with facts
        # Keep side_chat if no solid step completion signal
        if not facts and not obj.get("answered_current"):
            status = "side_chat"

    advance = status == "pass"
    answered = status == "pass"

    hint = str(obj.get("speech_hint") or "").strip() or _default_hint(status, kind)
    resume = str(obj.get("resume_hint") or "").strip()
    if not resume and status in ("side_chat", "clarify", "in_progress"):
        resume = "After handling this, clearly re-ask the current step question."
    emotion = str(obj.get("emotion") or "warm").strip() or "warm"

    return Understanding(
        step_status=status,  # type: ignore[arg-type]
        kind=kind,
        answered_current=answered,
        advance=advance,
        interrupt=interrupt,
        facts=facts,
        speech_hint=hint,
        resume_hint=resume,
        emotion=emotion,
        raw=obj,
    )


def _default_hint(status: str, kind: str) -> str:
    if status == "side_chat" or kind in ("question", "tangent"):
        return (
            "Handle their side topic warmly in one short sentence, then steer back "
            "to the current step question. Do not move to a new script step."
        )
    if status == "clarify" or kind in ("empty", "gibberish", "unclear"):
        return "Check in warmly and re-ask the current step with one example answer."
    if status == "in_progress":
        return "Acknowledge what they gave, then ask only for what's still missing on this step."
    if status == "fail":
        return "Close this path kindly based on the failure reason."
    return "Continue with the next required ask."


def _clean_facts(facts: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    bool_keys = (
        "decision_maker",
        "callback_ok",
        "soa_agreed",
        "nursing_home",
        "voice_signed",
        "medicaid_dual",
    )
    str_keys = (
        "current_plan",
        "plan_satisfaction",
        "doctor",
        "meds",
        "priorities",
        "other_coverage",
        "selected_plan_id",
        "address",
        "caller_name",
    )
    for k in bool_keys:
        if k in facts and facts[k] is not None:
            out[k] = bool(facts[k])
    for k in str_keys:
        if k in facts and facts[k] is not None and str(facts[k]).strip():
            val = str(facts[k]).strip()
            if k == "selected_plan_id" and val not in PLAN_IDS:
                continue
            if k == "other_coverage":
                val = val.lower().replace(" ", "_")
                if val not in ("none", "employer", "va", "tricare"):
                    continue
            out[k] = val
    if "conditions" in facts and facts["conditions"] is not None:
        c = facts["conditions"]
        if isinstance(c, list):
            out["conditions"] = [str(x) for x in c]
        elif isinstance(c, str) and c.strip():
            out["conditions"] = [c.strip()]
    if facts.get("_optimal"):
        out["_optimal"] = True
    return out


def _extract_json(text: str) -> dict[str, Any] | None:
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


def apply_facts_to_state(state: dict[str, Any], facts: dict[str, Any]) -> None:
    flags = state.setdefault(
        "flags",
        {"dnc": False, "abuse": False, "side_topic": False, "medicaid_dual": False},
    )
    mapping = (
        "decision_maker",
        "callback_ok",
        "soa_agreed",
        "current_plan",
        "plan_satisfaction",
        "doctor",
        "meds",
        "priorities",
        "nursing_home",
        "other_coverage",
        "selected_plan_id",
        "address",
        "caller_name",
        "voice_signed",
    )
    for k in mapping:
        if k in facts:
            state[k] = facts[k]
    if "conditions" in facts:
        state["conditions"] = facts["conditions"]
    if "medicaid_dual" in facts:
        flags["medicaid_dual"] = bool(facts["medicaid_dual"])
    if state.get("selected_plan_id") == "dual_food_snp":
        flags["medicaid_dual"] = True


def step_question_brief(step: str) -> str:
    briefs = {
        "intro": "Is now a good time to review their Medicare plan?",
        "disclaimers": "Do they agree to recorded call + continue the appointment (SOA)?",
        "soa": "Do they agree to Scope of Appointment / continue?",
        "ask_decision_maker": "Do they make their own healthcare decisions?",
        "ask_callback": "OK to call back on this number if the call drops?",
        "ask_satisfaction": "How do they like their current plan?",
        "ask_conditions": "Diabetes, blood clots, or stroke history?",
        "ask_doctor": "Do they see a primary doctor / how often?",
        "ask_meds": "Any regular medications?",
        "ask_priorities": "What matters most in coverage?",
        "ask_living": "Live at home or nursing/long-term care facility?",
        "ask_other_coverage": "Employer, VA, or TRICARE coverage?",
        "plan_review": "How does the recommended plan sound?",
        "dual_attestation": "Chronic attestation + PCP name/phone?",
        "plan_confirm": "Confirm they want to enroll in the selected plan?",
        "address": "Physical address for the application?",
        "enrollment_readback": "Agree to enrollment disclosures?",
        "voice_signature": "Name, DOB, today's date, and I agree?",
    }
    return briefs.get(step, f"Continue the closer at step {step}.")


def offline_understanding(step: str, text: str, state: dict[str, Any]) -> Understanding:
    """Offline fallback for automated tests — not used in live interactive."""
    raw = (text or "").strip()
    if not raw:
        return Understanding(
            step_status="clarify",
            kind="empty",
            speech_hint="Check they're still on the line, then re-ask simply.",
            resume_hint="Re-ask the current step.",
            emotion="patient",
        )
    t = raw.lower()

    if any(x in t for x in ("stop calling", "do not call", "remove me", "not interested")):
        return Understanding(
            step_status="fail",
            kind="interrupt",
            interrupt="dnc",
            advance=False,
            answered_current=False,
        )
    if "harass" in t or "scam" in t or "shut up" in t:
        return Understanding(
            step_status="fail" if state.get("_hostility") else "in_progress",
            kind="interrupt",
            interrupt="abuse" if state.get("_hostility") else "hostile",
            speech_hint="De-escalate calmly." if not state.get("_hostility") else "End calmly.",
        )
    if "isn't a good time" in t or "call me back later" in t or "busy right now" in t:
        return Understanding(
            step_status="fail",
            kind="interrupt",
            interrupt="callback",
        )

    # Side-chat / questions — stay for potentially many turns
    if (
        "?" in raw
        or t.startswith(("what ", "who ", "where ", "why ", "how "))
        or "last name" in t
        or "grandson" in t
        or "baseball" in t
    ):
        if not (
            ("agree" in t or "yes" in t)
            and step in ("disclaimers", "soa", "intro")
            and "what" not in t[:12]
        ):
            if "what is" in t or "who are" in t or "where is" in t or "last name" in t or "grandson" in t:
                return Understanding(
                    step_status="side_chat",
                    kind="question" if "?" in raw or t.startswith(("what", "who", "where")) else "tangent",
                    speech_hint="Answer or acknowledge briefly, then re-ask the current step.",
                    resume_hint="Steer back to the current step question.",
                    emotion="helpful",
                )

    facts: dict[str, Any] = {}
    if "agree" in t or "sounds good" in t or t in {"yes", "sure", "okay", "ok", "yep", "yeah", "suure", "suuuuure"}:
        if step in ("intro", "disclaimers", "soa"):
            facts["soa_agreed"] = True
        if step == "ask_callback":
            facts["callback_ok"] = True
        if step == "ask_decision_maker" or ("make" in t and "decision" in t):
            facts["decision_maker"] = True
    if "daughter" in t and "decision" in t:
        facts["decision_maker"] = False
    if "humana" in t:
        facts["current_plan"] = "Humana"
    if "aetna" in t:
        facts["current_plan"] = "Aetna"
    if "diabetes" in t and "what is" not in t and "what's" not in t:
        facts["conditions"] = ["diabetes"]
    if "no chronic" in t or (t == "none" and step == "ask_conditions"):
        facts["conditions"] = ["none"]
    if "no meds" in t or (t == "none" and step == "ask_meds"):
        facts["meds"] = "none"
    if "blood pressure" in t:
        facts["meds"] = "blood pressure medication"
    if "low cost" in t or "doesn't cost" in t or "dont cost" in t:
        facts["priorities"] = "low cost"
    if "dental" in t:
        facts["priorities"] = "dental/vision"
    if "food" in t:
        facts["priorities"] = "food card"
        facts["medicaid_dual"] = True
        facts["selected_plan_id"] = "dual_food_snp"
    if "medicaid" in t or "dual eligible" in t or "i'm dual" in t:
        facts["medicaid_dual"] = True
    if "live at home" in t or t in {"home", "at home"} or "at home" in t:
        facts["nursing_home"] = False
    if "nursing" in t and "where" not in t:
        facts["nursing_home"] = True
    if "no other coverage" in t or "no employer" in t or (
        t in {"no", "nope", "none"} and step == "ask_other_coverage"
    ):
        facts["other_coverage"] = "none"
    if ("employer" in t or "through my job" in t or "kept me on" in t) and "no employer" not in t:
        if not t.strip().startswith("no"):
            facts["other_coverage"] = "employer"
    if re.search(r"\bva\b", t):
        facts["other_coverage"] = "va"
    if "otc" in t:
        facts["selected_plan_id"] = "otc_zero"
    if re.search(r"\d+\s+\w+", raw) and any(x in t for x in ("street", "ave", "road", "main", "oak")):
        facts["address"] = raw[:120]
    if "i agree" in t and re.search(r"\d", raw):
        facts["voice_signed"] = True
    if "anything better" in t or "stay put" in t or "nothing better" in t:
        facts["priorities"] = facts.get("priorities") or "keep current"
        facts["_optimal"] = True

    # Callback no
    if step == "ask_callback" and t in {"no", "nope", "nah"}:
        facts["callback_ok"] = False

    return Understanding(
        step_status="pass",
        kind="answer",
        answered_current=True,
        advance=True,
        facts=facts,
        speech_hint="Continue naturally with the next required ask.",
        emotion="warm",
    )
