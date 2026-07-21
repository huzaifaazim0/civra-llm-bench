"""Voice-only prompts: LLM speaks; controller owns the flow.

Interactive latency mode can use fast canned lines (<1ms) for normal
script steps, and only call the LLM for side-chat / stay turns.
"""

from __future__ import annotations

from typing import Any

from controller import Directive
from plans import PLAN_BY_ID


def build_voice_system_prompt(
    *,
    agent_name: str = "Alex",
    broker_name: str = "Summit Senior Advisors",
    state_name: str = "Texas",
) -> str:
    return f"""You are {agent_name} Rivera, a licensed Medicare insurance agent with {broker_name} in {state_name}.
You are ON A LIVE PHONE CALL with a real person — often older, sometimes worried, frustrated, or chatty.
Another system already decided WHAT must happen this turn. Your ONLY job is HOW you say it.

If they ask who you are: you are {agent_name} Rivera with {broker_name}.
If they ask where you're located: {broker_name} is based in {state_name}.

Be emotionally intelligent:
- Mirror their energy: calm if anxious, gentle if confused, warm if friendly, steady if angry.
- Acknowledge feelings in one short clause before the ask ("I hear you…", "That makes sense…").
- Never sound like a script or a form. Never dump a checklist.
- Prefer contractions, everyday words, and natural pauses (use "…" sparingly).
- One clear question or ask at the end when the brief needs an answer.
- If the brief says they asked a question, ANSWER that question first, then return to the brief's ask.
- Never assume they have a condition just because they asked what it is.
- NEVER say "I didn't quite catch that" as a default. If something was unclear, acknowledge what you can and give a simple example of how they can answer.

Hard rules:
- Prefer ONE short sentence; never more than two.
- Match the requested emotion.
- Do NOT re-ask facts listed as already known.
- Do NOT invent plan names — only what the brief specifies.
- NEVER output JSON, markdown, stage directions, labels, or bullet lists — ONLY words you would speak aloud.
- Do not say you are an AI.
"""


def build_voice_turn_user(
    *,
    directive: Directive,
    caller_text: str,
    is_opening: bool = False,
) -> str:
    caller_bit = (
        "(call just connected — you speak first)"
        if is_opening
        else f'Caller just said: "{caller_text}"'
    )
    known = _known_facts(directive.state)
    side = ""
    if directive.side_topic:
        side = (
            "They went on a tangent — acknowledge the human moment briefly, then gently "
            "return to ONLY the question in the brief.\n"
        )
    return (
        f"{caller_bit}\n\n"
        f"{side}"
        f"Emotion to convey: {directive.emotion}\n"
        f"What you must accomplish this turn:\n{directive.speech_goal}\n\n"
        f"Already known (do NOT re-ask): {known}\n\n"
        "Speak now as the agent only (warm, human, emotionally aware):"
    )


def needs_llm_voice(directive: Directive) -> bool:
    """True when a canned line is not enough (side chat, clarify, de-escalate)."""
    if directive.side_topic or directive.stay_on_step:
        return True
    if (directive.emotion or "") in ("empathetic", "patient", "understanding") and (
        "side" in (directive.speech_goal or "").lower()
        or "tangent" in (directive.speech_goal or "").lower()
        or "unclear" in (directive.speech_goal or "").lower()
        or "re-ask" in (directive.speech_goal or "").lower()
    ):
        return True
    return False


def fast_spoken_line(
    directive: Directive,
    *,
    agent_name: str = "Alex",
    broker_name: str = "Summit Senior Advisors",
) -> str | None:
    """Instant canned speech for normal script steps. None → use LLM."""
    if needs_llm_voice(directive):
        return None

    state = directive.state or {}
    step = state.get("step") or directive.next or ""
    plan = PLAN_BY_ID.get(state.get("selected_plan_id") or "") or {}
    plan_name = plan.get("name") or "this plan"
    premium = plan.get("premium") or "$0"
    effective = state.get("effective_date") or "January 1, 2026"
    current = state.get("current_plan") or "your current plan"

    lines = {
        "intro": (
            f"Hi, I'm {agent_name} with {broker_name} — got a minute to review your "
            f"Medicare plan for 2026?"
        ),
        "disclaimers": (
            "Quick note: this call is recorded, and for every plan option you can use "
            "Medicare.gov or 1-800-Medicare. OK to continue?"
        ),
        "soa": (
            "Just confirming — I'm an independent broker and we may discuss Medicare "
            "Advantage, Part D, or supplements. OK to keep going?"
        ),
        "ask_decision_maker": (
            "Do you usually make your own healthcare decisions, or does someone help?"
        ),
        "ask_callback": "If we get disconnected, can I call you back at this number?",
        "ask_satisfaction": f"How have you been liking {current} so far?",
        "ask_conditions": (
            "Any diabetes, blood clots, or a past stroke I should know about?"
        ),
        "ask_doctor": "Do you see a primary doctor regularly?",
        "ask_meds": "Are you on any regular medications?",
        "ask_priorities": "What matters most in coverage for you — cost, dental, extras?",
        "ask_living": "Do you live at home, or in a nursing or long-term care facility?",
        "ask_other_coverage": (
            "Any other coverage through an employer, the VA, or TRICARE?"
        ),
        "plan_review": (
            f"Based on what you shared, {plan_name} looks like a strong fit — "
            f"{plan.get('headline') or 'solid benefits'}. How does that sound?"
        ),
        "dual_attestation": (
            "For this dual plan I need your condition confirmed plus your doctor's "
            "name and phone, and that you've seen them in the last two years."
        ),
        "plan_confirm": (
            f"Ready to enroll in {plan_name} at {premium}, starting {effective}?"
        ),
        "address": "What's the physical address we should use for the application?",
        "enrollment_readback": (
            "Quick enrollment check: one plan at a time, this replaces your current "
            "Medicare Advantage on the effective date, and your info is accurate — agree?"
        ),
        "voice_signature": (
            "For the recording, please say your full name, date of birth, today's date, "
            "and that you agree."
        ),
        "close_success": (
            f"You're set on {plan_name} starting {effective} — card in about three weeks. "
            "Thanks so much!"
        ),
        "close_employer_conflict": (
            "With employer coverage I can't enroll you today — check with benefits first, "
            "and I'm happy to help after."
        ),
        "close_not_decision_maker": (
            "I need to speak with whoever makes the healthcare decisions — "
            "can I get their name and a good callback time?"
        ),
        "close_optimal_current": (
            "Your current plan still looks best for 2026 — I'll note the file and I'm here if anything changes."
        ),
        "callback": "Got it — I'll call you back then. Take care!",
        "dnc": (
            "Understood — I'll remove you from our list right away. You can also use the "
            "National Do Not Call Registry at 1-888-382-1222. Goodbye."
        ),
        "end_abuse": "I'm sorry for the frustration — I won't call again. Goodbye.",
    }

    # Prefer controller step; fall back to next for terminals where step may be close_*
    key = step if step in lines else (directive.next or "")
    if key in lines:
        return lines[key]
    if directive.action != "continue" and key:
        # Terminal actions often use next=done with step=close_*
        for cand in (step, directive.next):
            if cand in lines:
                return lines[cand]
    return None


def _known_facts(state: dict[str, Any]) -> str:
    bits: list[str] = []
    if state.get("soa_agreed"):
        bits.append("SOA agreed")
    if state.get("decision_maker") is True:
        bits.append("makes own decisions")
    if state.get("decision_maker") is False:
        bits.append("NOT decision-maker")
    if state.get("callback_ok"):
        bits.append("callback OK")
    if state.get("current_plan"):
        bits.append(f"current plan={state['current_plan']}")
    if state.get("conditions"):
        bits.append(f"conditions={state['conditions']}")
    if state.get("meds"):
        bits.append(f"meds={state['meds']}")
    if state.get("priorities"):
        bits.append(f"priorities={state['priorities']}")
    if state.get("other_coverage"):
        bits.append(f"other_coverage={state['other_coverage']}")
    if state.get("selected_plan_id"):
        bits.append(f"selected_plan={state['selected_plan_id']}")
    if state.get("nursing_home") is False:
        bits.append("lives at home")
    if (state.get("flags") or {}).get("medicaid_dual"):
        bits.append("medicaid dual")
    return ", ".join(bits) if bits else "nothing solid yet"
