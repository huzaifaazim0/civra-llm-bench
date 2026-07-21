"""Code-owned Medicare closer dialog controller.

The LLM only writes natural spoken lines. This module owns step order,
state updates, plan selection, and terminal actions.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from plans import DEFAULT_EFFECTIVE_DATE, PLAN_BY_ID
from schema import empty_state
from understand import Understanding, apply_facts_to_state, offline_understanding, step_question_brief

# Core qualification order after SOA + decision-maker (optional verifies skipped).
QUAL_ORDER = (
    "ask_callback",
    "ask_satisfaction",
    "ask_conditions",
    "ask_doctor",
    "ask_meds",
    "ask_priorities",
    "ask_living",
    "ask_other_coverage",
    "plan_review",
)

ENROLL_ORDER = (
    "plan_confirm",
    "address",
    "enrollment_readback",
    "voice_signature",
)


@dataclass
class Directive:
    """What the agent should do this turn."""

    action: str
    next: str
    state: dict[str, Any]
    speech_goal: str
    emotion: str = "warm"
    stay_on_step: bool = False
    side_topic: bool = False


def _lower(text: str) -> str:
    return (text or "").strip().lower()


def _has_any(text: str, needles: list[str]) -> bool:
    t = _lower(text)
    return any(n.lower() in t for n in needles)


def detect_interrupt(text: str, *, hostility_strikes: int) -> str | None:
    """Return a terminal/special interrupt id, or None."""
    t = _lower(text)
    if not t:
        return None
    if _has_any(
        t,
        [
            "stop calling",
            "do not call",
            "don't call",
            "remove me",
            "take me off",
            "not interested",
            "never call",
        ],
    ):
        return "dnc"
    if _has_any(
        t,
        [
            "scam",
            "shut up",
            "harassing",
            "harass",
            "report you",
            "fbi",
            "damn",
            "idiot",
            "tired of all these",
            "don't know who you",
            "do not know who you",
            "every day someone",
            "who you people",
        ],
    ):
        return "abuse" if hostility_strikes >= 1 else "hostile"
    if _has_any(
        t,
        [
            "not a good time",
            "call me back later",
            "busy right now",
            "this isn't a good time",
            "call me later",
            "now isn't a good",
            "not a good time",
        ],
    ) or (
        _has_any(t, ["call me back", "call back"])
        and _has_any(t, ["later", "another time", "bad time", "busy", "not a good"])
    ):
        return "callback"
    return None


def _yes(text: str) -> bool:
    t = _lower(text)
    return _has_any(
        t,
        [
            "yes",
            "yeah",
            "yep",
            "sure",
            "okay",
            "i agree",
            "sounds good",
            "go ahead",
            "i do",
            "correct",
            "that's right",
            "that is right",
            "please do",
            "fine.",
            "i guess",
        ],
    ) or t in {"ok", "y", "yea", "fine"}


def _soa_accept(text: str, step: str) -> bool:
    """Caller accepted SOA / recording / appointment continue."""
    t = _lower(text)
    if "disagree" in t:
        return False
    # Intro "sure / go ahead" only means willing to talk — disclaimers+SOA still required
    if step == "intro":
        return bool(
            re.search(r"\bagree\b", t)
            and _has_any(t, ["soa", "appointment", "recorded", "scope", "continue the"])
        )
    if re.search(r"\bagree\b", t):
        return True
    strong = _has_any(
        t,
        [
            "soa",
            "scope of",
            "appointment",
            "recorded",
            "continue",
        ],
    )
    if strong:
        return True
    # Soft yes on disclaimers/soa completes SOA (those turns ask for it)
    if step in ("disclaimers", "soa") and _yes(t):
        return True
    return False


def _wants_optimal_current(text: str) -> bool:
    t = _lower(text)
    return _has_any(
        t,
        [
            "anything better",
            "nothing better",
            "stay put",
            "keep my",
            "stay with my",
            "i'll stay",
            "ill stay",
            "love my current",
            "happy with my",
            "happy —",
            "happy -",
            "fine as is",
            "stay put",
        ],
    )


def _topic_overlay(text: str, state: dict[str, Any]) -> tuple[str, str | None]:
    """Extra spoken guidance for emotional / explanatory moments. (prefix, emotion)."""
    t = _lower(text)
    flags = state.get("flags") or {}
    if _has_any(t, ["social security", "ssn", "social"]) and _has_any(
        t, ["don't", "do not", "won't", "not give", "can't give", "refuse"]
    ):
        return (
            "Empathize: you understand they don't want to share SSN. Reassure you can often "
            "pull dual/Medicaid info another way, or wait until they find their card. Soft, no pressure. ",
            "empathetic",
        )
    if _has_any(t, ["cash back", "giveback", "give back", "part b reduction"]):
        return (
            "Explain warmly: with Medicaid, Part B giveback usually isn't available — instead "
            "dual plans often include food/utility card and dental. Then ask the next question. ",
            "helpful",
        )
    if (state.get("other_coverage") == "va" or "va benefit" in t or "va benefits" in t) and not _has_any(
        t, ["no", "don't"]
    ):
        return (
            "Acknowledge VA benefits work separately and can coordinate with Medicare; "
            "reassure you're careful not to disrupt VA. ",
            "reassuring",
        )
    if _has_any(t, ["no doctors", "no doctor", "up here in the country", "rural", "out in the country"]):
        return (
            "Empathize about limited doctors nearby. Say you'll focus on network/PPO options "
            "near their home/town. ",
            "empathetic",
        )
    if flags.get("medicaid_dual") and _has_any(t, ["food card", "food and utility", "dual"]):
        return (
            "Affirm the dual SNP food/utility card direction enthusiastically but calmly. ",
            "encouraging",
        )
    return ("", None)


def _no(text: str) -> bool:
    t = _lower(text)
    if _yes(t) and "no" not in t.split():
        # "yes I make my own" shouldn't count as no
        pass
    return _has_any(
        t,
        [" no", "no,", "no.", "no ", "not really", "nah", "don't", "do not"],
    ) or t in {"no", "nope", "nah"}


def apply_caller_facts(state: dict[str, Any], text: str) -> None:
    """Update state with facts mentioned anywhere in the caller utterance."""
    t = _lower(text)
    flags = state.setdefault(
        "flags",
        {"dnc": False, "abuse": False, "side_topic": False, "medicaid_dual": False},
    )

    if _has_any(t, ["medicaid", "dual eligible", "dual-eligible", "i'm dual", "im dual", "dual eligible"]):
        flags["medicaid_dual"] = True

    for plan in ("humana", "aetna", "united", "cigna", "anthem", "wellcare"):
        if plan in t:
            state["current_plan"] = plan.title() if plan != "united" else "United"

    if _has_any(t, ["no chronic", "no conditions", "none of those", "don't have diabetes", "no diabetes"]):
        if not _has_any(t, ["i have diabetes", "have diabetes", "i'm diabetic", "im diabetic"]):
            state["conditions"] = ["none"]

    if _has_any(t, ["diabetes", "diabetic"]):
        conds = [c for c in (state.get("conditions") or []) if c != "none"]
        if not any("diabet" in c.lower() for c in conds):
            conds.append("diabetes")
        state["conditions"] = conds
    if _has_any(t, ["stroke", "blood clot", "heart failure"]):
        conds = [c for c in (state.get("conditions") or []) if c != "none"]
        for c in ("stroke", "blood clot", "heart failure"):
            if c in t and c not in conds:
                conds.append(c)
        state["conditions"] = conds

    if _has_any(t, ["no meds", "no medication", "not on any med", "don't take med"]):
        state["meds"] = "none"
    elif _has_any(t, ["medication", "meds", "blood pressure", "prescription"]):
        if "blood pressure" in t:
            state["meds"] = "blood pressure medication"
        elif state.get("meds") is None:
            state["meds"] = "prescriptions mentioned"

    if _has_any(t, ["doesn't cost", "dont cost", "low cost", "cheap", "affordable", "otc"]):
        state["priorities"] = "low cost"
    if _has_any(t, ["food card", "food and utility", "u-card", "ucard", "food and utility benefits"]):
        state["priorities"] = "food card"
        flags["medicaid_dual"] = True
        # Only lock plan id after SOA (schema normalize strips earlier)
        if state.get("soa_agreed") is True:
            state["selected_plan_id"] = "dual_food_snp"
    if _wants_optimal_current(t):
        state["priorities"] = state.get("priorities") or "keep current"

    if _has_any(t, ["nursing home", "long-term care", "long term care"]) or t.strip() in {
        "nursing",
        "facility",
    }:
        state["nursing_home"] = True
    elif _has_any(t, ["live at home", "own home", "live in my"]) or t.strip() in {"home"}:
        state["nursing_home"] = False

    # Bare "none" / "nope" often answers conditions or coverage depending on step — also store softly
    if t.strip() in {"none", "nothing"} and not state.get("conditions"):
        # Don't overwrite later; step commit is authoritative
        pass

    if t.strip().isdigit() and state.get("meds") is None:
        # likely med count when on meds step — commit_step handles; soft store
        pass

    # Other coverage — check negatives BEFORE positives ("no ... through work")
    if _has_any(
        t,
        [
            "no other coverage",
            "no employer",
            "don't have employer",
            "do not have employer",
            "no coverage through",
            "no other",
            "without employer",
        ],
    ) or (
        "no" in t
        and _has_any(t, ["through work", "through my job", "employer", "va", "tricare"])
        and _has_any(t, ["coverage", "insurance", "work", "job", "va", "tricare"])
    ):
        # "No other coverage through work or VA"
        if not _has_any(t, ["still have", "i have insurance through", "kept me on"]):
            state["other_coverage"] = "none"
    elif _has_any(t, ["employer", "through my job", "through work", "retiree", "kept me on"]):
        state["other_coverage"] = "employer"
    elif _has_any(t, [" tricare", "tricare"]):
        state["other_coverage"] = "tricare"
    elif re.search(r"\bva\b", t) or "veterans" in t:
        state["other_coverage"] = "va"
    elif _has_any(t, ["live at home"]) and state.get("other_coverage") is None:
        pass  # don't infer coverage from living alone

    if _has_any(t, ["daughter", "son handles", "someone else", "my kids make"]):
        if "i make" not in t and "my own" not in t:
            state["decision_maker"] = False

    if _has_any(
        t,
        [
            "i make my own",
            "i make all",
            "yes i make",
            "i decide for myself",
            "i decide",
            "i make decisions",
            "make decisions",
            "i make the decisions",
            "most of the time",
        ],
    ):
        if not _has_any(t, ["daughter", "son handles", "someone else"]):
            state["decision_maker"] = True

    # Address-ish
    if re.search(r"\d+\s+\w+", text) and _has_any(t, ["street", "ave", "road", "dr", "lane", "main"]):
        state["address"] = text.strip()[:120]

    # Voice signature cues
    if _has_any(t, ["i agree"]) and re.search(r"\d{4}", text):
        state["voice_signed"] = True
        # try name
        m = re.search(r"([A-Z][a-z]+\s+[A-Z][a-z]+)", text)
        if m:
            state["caller_name"] = m.group(1)

    if _has_any(t, ["dr.", "doctor"]) and re.search(r"\d{3}", text):
        state["doctor"] = text.strip()[:100]


def _answers_current_step(step: str, text: str) -> bool:
    """Heuristic: did the caller address the current question?"""
    t = _lower(text)
    if not t:
        return False
    if detect_interrupt(text, hostility_strikes=0) in ("dnc", "callback", "abuse", "hostile"):
        return True
    if step in ("intro", "disclaimers", "soa"):
        return _yes(t) or _has_any(t, ["agree", "continue", "sounds good", "go ahead", "sure"])
    if step == "ask_decision_maker":
        return _has_any(
            t,
            ["make my own", "i decide", "my own", "daughter", "son", "someone else", "yes", "no"],
        )
    if step == "ask_callback":
        return _yes(t) or _has_any(t, ["number", "call", "thursday", "pm", "am", "same"])
    if step == "ask_satisfaction":
        return _has_any(t, ["fine", "good", "okay", "ok", "humana", "aetna", "united", "love", "hate", "plan"])
    if step == "ask_conditions":
        return _has_any(t, ["diabetes", "stroke", "clot", "no", "none", "healthy", "heart"])
    if step == "ask_doctor":
        return _has_any(t, ["doctor", "often", "seldom", "never", "rarely", "pcp", "dr"])
    if step == "ask_meds":
        return _has_any(t, ["med", "prescription", "blood pressure", "none", "no ", "just"])
    if step == "ask_priorities":
        return _has_any(t, ["cost", "dental", "cash", "food", "best", "whatever", "low", "otc"])
    if step == "ask_living":
        return _has_any(t, ["home", "nursing", "facility", "live"])
    if step == "ask_other_coverage":
        return _has_any(t, ["employer", "job", "work", "va", "tricare", "no other", "none", "no,"])
    if step == "plan_review":
        return _has_any(t, ["sound", "good", "let's", "lets", "do it", "enroll", "otc", "food", "yes", "no", "better"])
    if step == "dual_attestation":
        return _has_any(t, ["attest", "diabetes", "doctor", "dr", "phone", "555"])
    if step in ("plan_confirm", "enrollment_readback"):
        return _yes(t) or _has_any(t, ["agree", "yes"])
    if step == "address":
        return bool(re.search(r"\d+", text)) or _has_any(t, ["street", "ave", "road"])
    if step == "voice_signature":
        return _has_any(t, ["agree"]) and bool(re.search(r"\d", text))
    return _yes(t) or len(t.split()) > 2


def choose_plan(state: dict[str, Any]) -> str:
    flags = state.get("flags") or {}
    if flags.get("medicaid_dual") or (state.get("priorities") or "").find("food") >= 0:
        return "dual_food_snp"
    conds = " ".join(state.get("conditions") or []).lower()
    pri = (state.get("priorities") or "").lower()
    if "diabet" in conds or "low cost" in pri or "otc" in pri or "cost" in pri:
        return "otc_zero"
    if state.get("plan_satisfaction") == "poor" and "comprehensive" not in pri:
        # Unhappy on cost/value → prefer OTC zero-premium
        return "otc_zero"
    return "giveback_ppo"


def next_after(step: str, state: dict[str, Any]) -> str:
    """Advance one step in the scripted order."""
    if step in ("intro",):
        return "disclaimers"
    if step == "disclaimers":
        return "soa"
    if step == "soa":
        return "ask_decision_maker"
    if step == "ask_decision_maker":
        return "ask_callback"
    if step in QUAL_ORDER:
        idx = QUAL_ORDER.index(step)
        if step == "ask_other_coverage":
            return "plan_review"
        if step == "plan_review":
            pid = state.get("selected_plan_id") or choose_plan(state)
            state["selected_plan_id"] = pid
            plan = PLAN_BY_ID.get(pid) or {}
            if plan.get("requires_chronic_attestation") or pid == "dual_food_snp":
                return "dual_attestation"
            return "plan_confirm"
        return QUAL_ORDER[idx + 1]
    if step == "dual_attestation":
        return "plan_confirm"
    if step in ENROLL_ORDER:
        idx = ENROLL_ORDER.index(step)
        if idx + 1 < len(ENROLL_ORDER):
            return ENROLL_ORDER[idx + 1]
        return "close_success"
    if step == "close_success":
        return "done"
    return "ask_satisfaction"


def speech_brief_for_step(step: str, state: dict[str, Any], *, side_topic: bool = False) -> tuple[str, str]:
    """Return (speech_goal, emotion)."""
    agent_bits = []
    if side_topic:
        agent_bits.append(
            "Briefly acknowledge what they shared with genuine warmth (one short clause), "
            "then steer back — ask ONLY the current question below. Do not restart the whole script."
        )
        emotion = "empathetic"
    else:
        emotion = "warm"

    plan = PLAN_BY_ID.get(state.get("selected_plan_id") or "") or {}
    name = state.get("caller_name") or "there"

    goals = {
        "intro": (
            "Outbound opener in ONE short sentence: licensed agent, review plan for 2026, ask if now is OK. No pitch."
        ),
        "disclaimers": (
            "ONE short sentence: call is recorded; for all plans use Medicare.gov or 1-800-Medicare. "
            "Ask if they agree to continue. No pitch."
        ),
        "soa": (
            "Confirm Scope of Appointment in plain language: independent broker, may discuss "
            "Medicare Advantage, Part D, supplements — do they agree to continue? One clear ask."
        ),
        "ask_decision_maker": (
            "Ask warmly if they make their own healthcare decisions, or if someone else helps."
        ),
        "ask_callback": (
            "Ask if you can call them back at this number if the call drops. Keep it light."
        ),
        "ask_satisfaction": (
            f"You see they're on {state.get('current_plan') or 'their current plan'}. "
            "Ask how they've been liking that plan — open and conversational."
        ),
        "ask_conditions": (
            "Ask if they have diabetes, blood clots, or ever had a stroke "
            "(chronic plan screening). Soft, not clinical."
        ),
        "ask_doctor": (
            "Ask if they see a primary doctor regularly and how often — curious, not checklist-y."
        ),
        "ask_meds": "Ask if they're on any regular medications. Brief.",
        "ask_priorities": (
            "Ask what matters most in coverage — cost, dental, extra benefits, etc. Invite their words."
        ),
        "ask_living": "Ask if they live at home or in a nursing/long-term care facility.",
        "ask_other_coverage": (
            "Ask if they have other coverage through an employer, the VA, or TRICARE."
        ),
        "plan_review": (
            f"Present ONLY this plan in plain spoken language: {plan.get('name')} ({state.get('selected_plan_id')}). "
            f"Headline: {plan.get('headline')}. Mention 1–2 benefits. Ask how that sounds. "
            "Do not list other catalog plans unless they object."
        ),
        "dual_attestation": (
            "For the dual SNP: confirm their chronic condition and ask for primary doctor's name/phone "
            "and that they've seen them in the last two years."
        ),
        "plan_confirm": (
            f"Confirm they want to enroll in {plan.get('name')} with premium {plan.get('premium')} "
            f"effective {state.get('effective_date') or DEFAULT_EFFECTIVE_DATE}. Get a clear yes."
        ),
        "address": "Ask for their physical address to start the application. Friendly.",
        "enrollment_readback": (
            "Briefly cover enrollment disclosures in conversational voice (one plan at a time, "
            "effective date replaces current MA coverage, info is true, annual election). Ask if they agree."
        ),
        "voice_signature": (
            "Ask them to state full name, date of birth, today's date, and that they agree — for the recording."
        ),
        "close_success": (
            f"Warm success close: enrolled in {plan.get('name')}, effective "
            f"{state.get('effective_date') or DEFAULT_EFFECTIVE_DATE}, card in ~3 weeks, thank them."
        ),
        "close_employer_conflict": (
            "Firm but kind: employer coverage means you must NOT enroll them. Advise checking with "
            "employer benefits first. Offer to help later if they get the all-clear. End warmly."
        ),
        "close_not_decision_maker": (
            "Kindly explain you need the person who makes healthcare decisions. Ask for name/callback time."
        ),
        "close_optimal_current": (
            "Reassure their current plan still looks best for 2026; you'll note the file; offer future help."
        ),
        "callback": "Confirm the callback day/time and number. Short and clear. Wish them well.",
        "dnc": (
            "Respectful DNC close: remove from call list immediately. Mention they can also use the "
            "National Do Not Call Registry at 1-888-382-1222. Do NOT say that number is your office line."
        ),
        "end_abuse": (
            "Calm end: you won't call again. Brief apology for the frustration. No pitch. Goodbye."
        ),
        "deescalate": (
            f"Caller is frustrated. Empathize sincerely, introduce yourself briefly, no pressure. "
            "Offer to keep it short or call another time. Then ask one gentle next question for step: "
            f"{state.get('step')}."
        ),
    }

    goal = goals.get(step) or f"Continue the closer call at step {step}. Ask one clear question."
    if agent_bits:
        goal = agent_bits[0] + " " + goal
    if name and name != "there" and step == "intro":
        goal = f"Caller's first name may be {name}. " + goal
    return goal, emotion


class CloserController:
    """Mutable session controller."""

    def __init__(self, *, effective_date: str = DEFAULT_EFFECTIVE_DATE) -> None:
        self.state = empty_state("intro")
        self.state["effective_date"] = effective_date
        self.hostility_strikes = 0
        self.awaiting_callback_time = False
        self._opened = False
        # Multi-turn side chat: stay anchored on a step until LLM says pass
        self.side_chat_active = False
        self.side_chat_depth = 0
        self.anchor_step: str | None = None
        self.last_step_status: str = "in_progress"

    def opening(self) -> Directive:
        self._opened = True
        self.state["step"] = "intro"
        goal, emotion = speech_brief_for_step("intro", self.state)
        return Directive(
            action="continue",
            next="disclaimers",
            state=copy.deepcopy(self.state),
            speech_goal=goal,
            emotion=emotion,
        )

    def handle(self, caller_text: str, understanding: Understanding | None = None) -> Directive:
        """Advance only when LLM reports step_status=pass; side chats can span many turns."""
        text = caller_text or ""
        step = self.state.get("step") or "intro"
        if understanding is None:
            understanding = offline_understanding(step, text, self.state)

        apply_facts_to_state(self.state, understanding.facts)
        step = self.state.get("step") or "intro"
        if self.anchor_step and self.side_chat_active:
            step = self.anchor_step
            self.state["step"] = step

        hint = understanding.speech_hint or ""
        resume = understanding.resume_hint or ""
        emotion = understanding.emotion or "warm"
        status = understanding.step_status
        self.last_step_status = status

        interrupt = understanding.interrupt
        if interrupt == "dnc":
            self._clear_side_chat()
            return self._terminal("dnc", dnc=True)
        if interrupt == "callback":
            self._clear_side_chat()
            self.awaiting_callback_time = True
            if any(x in text.lower() for x in ("thursday", "monday", "tuesday", "wednesday", "friday", "pm", "am")):
                return self._terminal("callback")
            self.state["step"] = "ask_callback"
            return Directive(
                action="continue",
                next="ask_callback",
                state=copy.deepcopy(self.state),
                speech_goal=hint
                or "They said it's a bad time. Warmly ask what day and time works better. Do not pitch.",
                emotion="understanding",
            )
        if interrupt == "hostile":
            self.hostility_strikes += 1
            if self.hostility_strikes >= 2:
                self._clear_side_chat()
                return self._terminal("end_abuse", abuse=True)
            goal, emo = speech_brief_for_step("deescalate", self.state)
            return Directive(
                action="continue",
                next=step if step != "intro" else "disclaimers",
                state=copy.deepcopy(self.state),
                speech_goal=(hint + " " + goal).strip(),
                emotion=emotion or emo,
                stay_on_step=True,
            )
        if interrupt == "abuse":
            self._clear_side_chat()
            return self._terminal("end_abuse", abuse=True)

        if self.awaiting_callback_time and any(
            x in text.lower() for x in ("thursday", "monday", "tuesday", "wednesday", "friday", "pm", "am", "works")
        ):
            self._clear_side_chat()
            return self._terminal("callback")

        if status == "fail":
            self._clear_side_chat()
            if self.state.get("decision_maker") is False:
                return self._terminal("close_not_decision_maker")
            if self.state.get("other_coverage") == "employer" and self.state.get("soa_agreed"):
                return self._terminal("close_employer_conflict")
            if understanding.facts.get("_optimal") or (self.state.get("priorities") or "") == "keep current":
                return self._terminal("close_optimal_current")
            goal, emo = speech_brief_for_step(step, self.state)
            return Directive(
                action="continue",
                next=step,
                state=copy.deepcopy(self.state),
                speech_goal=(hint + " " + goal).strip(),
                emotion=emotion or emo,
                stay_on_step=True,
            )

        if self.state.get("decision_maker") is False and step not in ("intro",):
            self._clear_side_chat()
            return self._terminal("close_not_decision_maker")
        if (
            self.state.get("other_coverage") == "employer"
            and self.state.get("soa_agreed") is True
            and step not in ("intro", "close", "close_success")
        ):
            self._clear_side_chat()
            return self._terminal("close_employer_conflict")

        if understanding.facts.get("_optimal") and status == "pass":
            self._clear_side_chat()
            return self._terminal("close_optimal_current")

        if status in ("side_chat", "clarify", "in_progress") or understanding.stay:
            if status == "side_chat":
                if not self.side_chat_active:
                    self.side_chat_active = True
                    self.anchor_step = step
                    self.side_chat_depth = 0
                self.side_chat_depth += 1
                self.state["flags"]["side_topic"] = True
            else:
                if self.side_chat_active:
                    self.side_chat_depth += 1
                self.state["flags"]["side_topic"] = self.side_chat_active

            if status == "in_progress" and step in ("plan_review", "plan_confirm"):
                if (
                    (self.state.get("priorities") or "").find("low") >= 0
                    or "cost" in text.lower()
                    or "expensive" in text.lower()
                ):
                    if not (self.state.get("flags") or {}).get("medicaid_dual"):
                        self.state["selected_plan_id"] = "otc_zero"
                        self.state["priorities"] = self.state.get("priorities") or "low cost"
                self.state["step"] = "plan_review"
                goal, emo = speech_brief_for_step("plan_review", self.state)
                coach = " ".join(x for x in (hint, resume, goal) if x).strip()
                return Directive(
                    action="continue",
                    next="plan_review",
                    state=copy.deepcopy(self.state),
                    speech_goal=coach,
                    emotion=emotion or emo,
                    stay_on_step=True,
                )

            goal, emo = speech_brief_for_step(
                step, self.state, side_topic=(status == "side_chat" or self.side_chat_active)
            )
            depth_note = ""
            if self.side_chat_active and self.side_chat_depth > 1:
                depth_note = (
                    f" Still on step '{step}' after {self.side_chat_depth} side-chat turns — "
                    "acknowledge them, then kindly return to the step question. "
                )
            coach = " ".join(x for x in (hint, depth_note, resume, goal) if x).strip()
            return Directive(
                action="continue",
                next=step,
                state=copy.deepcopy(self.state),
                speech_goal=coach,
                emotion=emotion or emo,
                stay_on_step=True,
                side_topic=(status == "side_chat" or self.side_chat_active),
            )

        # pass → advance
        self._clear_side_chat()
        self.state["flags"]["side_topic"] = False
        overlay = hint

        if step in ("intro", "disclaimers", "soa"):
            if step == "intro":
                if self.state.get("soa_agreed") and self.state.get("decision_maker") is True:
                    return self._after_soa(overlay=overlay, emotion=emotion)
                if self.state.get("soa_agreed"):
                    return self._directive_for("ask_decision_maker", overlay=overlay, emotion=emotion)
                return self._directive_for("disclaimers", overlay=overlay, emotion=emotion)
            self.state["soa_agreed"] = True
            if self.state.get("decision_maker") is False:
                return self._terminal("close_not_decision_maker")
            if self.state.get("decision_maker") is True:
                return self._after_soa(overlay=overlay, emotion=emotion)
            return self._directive_for("ask_decision_maker", overlay=overlay, emotion=emotion)

        if step == "ask_decision_maker":
            if self.state.get("decision_maker") is False:
                return self._terminal("close_not_decision_maker")
            self.state["decision_maker"] = True
            return self._after_soa(overlay=overlay, emotion=emotion)

        if (
            self.state.get("soa_agreed")
            and self.state.get("decision_maker") is True
            and self.state.get("selected_plan_id")
            and status == "pass"
            and any(x in text.lower() for x in ("enroll", "food card", "sounds better", "let's do", "lets do"))
        ):
            if self.state.get("voice_signed") and self.state.get("address"):
                self.state["step"] = "close_success"
                return Directive(
                    action="enroll_success",
                    next="done",
                    state=copy.deepcopy(self.state),
                    speech_goal=speech_brief_for_step("close_success", self.state)[0],
                    emotion="celebratory",
                )
            nxt = next_after("plan_review", self.state)
            return self._directive_for(nxt, overlay=overlay, emotion=emotion)

        if step == "ask_other_coverage":
            if self.state.get("other_coverage") == "employer":
                return self._terminal("close_employer_conflict")
            if self.state.get("other_coverage") is None:
                self.state["other_coverage"] = "none"
            self.state["selected_plan_id"] = self.state.get("selected_plan_id") or choose_plan(self.state)
            return self._directive_for("plan_review", overlay=overlay, emotion=emotion)

        if step == "plan_review":
            if any(x in text.lower() for x in ("keep current", "stay", "nothing better", "no thanks")):
                return self._terminal("close_optimal_current")
            self.state["selected_plan_id"] = self.state.get("selected_plan_id") or choose_plan(self.state)
            nxt = next_after("plan_review", self.state)
            return self._directive_for(nxt, overlay=overlay, emotion=emotion)

        if step == "plan_confirm":
            if self.state.get("address") or understanding.facts.get("address"):
                return self._advance_from("address", overlay=overlay, emotion=emotion)
            if understanding.facts.get("voice_signed"):
                self.state["voice_signed"] = True
                self.state["step"] = "close_success"
                return Directive(
                    action="enroll_success",
                    next="done",
                    state=copy.deepcopy(self.state),
                    speech_goal=speech_brief_for_step("close_success", self.state)[0],
                    emotion="celebratory",
                )
            return self._advance_from("plan_confirm", overlay=overlay, emotion=emotion)

        if step == "enrollment_readback":
            if understanding.facts.get("voice_signed"):
                self.state["voice_signed"] = True
                self.state["soa_agreed"] = True
                self.state["step"] = "close_success"
                return Directive(
                    action="enroll_success",
                    next="done",
                    state=copy.deepcopy(self.state),
                    speech_goal=speech_brief_for_step("close_success", self.state)[0],
                    emotion="celebratory",
                )
            return self._advance_from("enrollment_readback", overlay=overlay, emotion=emotion)

        if step == "voice_signature":
            self.state["voice_signed"] = True
            self.state["soa_agreed"] = True
            if not self.state.get("selected_plan_id"):
                self.state["selected_plan_id"] = choose_plan(self.state)
            self.state["step"] = "close_success"
            return Directive(
                action="enroll_success",
                next="done",
                state=copy.deepcopy(self.state),
                speech_goal=speech_brief_for_step("close_success", self.state)[0],
                emotion="celebratory",
            )

        if step == "ask_priorities" and (self.state.get("priorities") or "") == "keep current":
            return self._terminal("close_optimal_current")

        if step in QUAL_ORDER and self.state.get("other_coverage") is not None and (
            self.state.get("priorities") or self.state.get("selected_plan_id")
        ):
            if self.state.get("other_coverage") == "employer":
                return self._terminal("close_employer_conflict")
            self.state["selected_plan_id"] = self.state.get("selected_plan_id") or choose_plan(self.state)
            nxt = "dual_attestation" if self.state["selected_plan_id"] == "dual_food_snp" else "plan_review"
            if step in (
                "ask_living",
                "ask_other_coverage",
                "ask_priorities",
                "ask_meds",
                "ask_doctor",
                "ask_conditions",
                "ask_callback",
                "ask_satisfaction",
            ) and len(text.split()) > 8:
                return self._directive_for(nxt, overlay=overlay, emotion=emotion)

        return self._advance_from(step, overlay=overlay, emotion=emotion)

    def _clear_side_chat(self) -> None:
        self.side_chat_active = False
        self.side_chat_depth = 0
        self.anchor_step = None
        if self.state.get("flags"):
            self.state["flags"]["side_topic"] = False

    def current_step_question(self) -> str:
        return step_question_brief(self.state.get("step") or "intro")

    def _directive_for(
        self,
        step: str,
        *,
        stay: bool = False,
        overlay: str = "",
        emotion: str | None = None,
    ) -> Directive:
        self.state["step"] = step
        goal, emo = speech_brief_for_step(step, self.state)
        if overlay:
            goal = overlay + goal
        return Directive(
            action="continue",
            next=step,
            state=copy.deepcopy(self.state),
            speech_goal=goal,
            emotion=emotion or emo,
            stay_on_step=stay,
        )

    def _after_soa(self, *, overlay: str = "", emotion: str | None = None) -> Directive:
        """Land on first unsatisfied qual step after SOA + DM."""
        if self.state.get("other_coverage") == "employer":
            return self._terminal("close_employer_conflict")
        if _wants_optimal_current(" ".join(filter(None, [self.state.get("priorities"), ""]))):
            # priorities may be keep current from prior utterance — only close if explicit this turn handled elsewhere
            pass
        # Start skip from ask_callback
        self.state["step"] = "ask_callback"
        nxt = resolve_next_step("ask_decision_maker", self.state)
        # resolve_next_step from ask_decision_maker → ask_callback then skips
        if nxt == "ask_callback" and step_already_satisfied("ask_callback", self.state):
            nxt = resolve_next_step("ask_callback", self.state)
        # If enough to review plans already
        if (
            self.state.get("other_coverage") is not None
            and (self.state.get("priorities") or self.state.get("conditions") is not None)
            and nxt in ("ask_callback", "ask_satisfaction", "ask_conditions", "ask_doctor", "ask_meds", "ask_priorities", "ask_living")
        ):
            # Prefer jumping when coverage + priority/conditions known
            if self.state.get("other_coverage") is not None and self.state.get("priorities"):
                self.state["selected_plan_id"] = choose_plan(self.state)
                nxt = "plan_review"
                if (self.state.get("selected_plan_id") == "dual_food_snp") and self.state.get("conditions"):
                    if "diabet" in " ".join(self.state.get("conditions") or []).lower():
                        # May still need attestation later
                        pass
        if nxt == "plan_review":
            self.state["selected_plan_id"] = choose_plan(self.state)
        return self._directive_for(nxt, overlay=overlay, emotion=emotion)

    def _advance_from(
        self,
        step: str,
        *,
        overlay: str = "",
        emotion: str | None = None,
    ) -> Directive:
        if self.state.get("other_coverage") == "employer" and step in (
            "ask_living",
            "ask_priorities",
            "ask_other_coverage",
            "ask_meds",
            "ask_doctor",
            "ask_conditions",
            "ask_satisfaction",
            "ask_callback",
        ):
            return self._terminal("close_employer_conflict")

        nxt = resolve_next_step(step, self.state)
        if nxt == "ask_other_coverage" and self.state.get("other_coverage") == "employer":
            return self._terminal("close_employer_conflict")
        if nxt == "plan_review":
            if self.state.get("other_coverage") == "employer":
                return self._terminal("close_employer_conflict")
            if not self.state.get("selected_plan_id"):
                self.state["selected_plan_id"] = choose_plan(self.state)
            # Prefer dual when medicaid
            if (self.state.get("flags") or {}).get("medicaid_dual"):
                self.state["selected_plan_id"] = "dual_food_snp"

        self.state["step"] = nxt if nxt != "done" else "close_success"
        goal, emo = speech_brief_for_step(self.state["step"], self.state)
        if overlay:
            goal = overlay + goal
        action = "continue"
        next_val = self.state["step"]
        if self.state["step"] == "close_success" and self.state.get("voice_signed"):
            action = "enroll_success"
            next_val = "done"
        return Directive(
            action=action,
            next=next_val,
            state=copy.deepcopy(self.state),
            speech_goal=goal,
            emotion=emotion or emo,
        )

    def _terminal(
        self,
        kind: str,
        *,
        dnc: bool = False,
        abuse: bool = False,
    ) -> Directive:
        self.state["step"] = "close"
        flags = self.state["flags"]
        if dnc or kind == "dnc":
            flags["dnc"] = True
            action = "dnc"
            goal_key = "dnc"
        elif abuse or kind == "end_abuse":
            flags["abuse"] = True
            action = "end_abuse"
            goal_key = "end_abuse"
        elif kind == "callback":
            action = "callback"
            goal_key = "callback"
        elif kind == "close_employer_conflict":
            self.state["other_coverage"] = "employer"
            action = "close_employer_conflict"
            goal_key = "close_employer_conflict"
        elif kind == "close_not_decision_maker":
            self.state["decision_maker"] = False
            action = "close_not_decision_maker"
            goal_key = "close_not_decision_maker"
        elif kind == "close_optimal_current":
            action = "close_optimal_current"
            goal_key = "close_optimal_current"
        else:
            action = "dnc"
            goal_key = "dnc"
        goal, emotion = speech_brief_for_step(goal_key, self.state)
        return Directive(
            action=action,
            next="done",
            state=copy.deepcopy(self.state),
            speech_goal=goal,
            emotion=emotion,
        )


def step_already_satisfied(step: str, state: dict[str, Any]) -> bool:
    """True if we can skip asking this step because state already has the answer."""
    if step == "ask_callback" and state.get("callback_ok") is True:
        return True
    if step == "ask_satisfaction" and state.get("current_plan"):
        return True
    if step == "ask_conditions" and isinstance(state.get("conditions"), list) and len(state["conditions"]) > 0:
        return True
    if step == "ask_doctor" and state.get("doctor"):
        return True
    if step == "ask_meds" and state.get("meds") is not None:
        return True
    if step == "ask_priorities" and state.get("priorities"):
        return True
    if step == "ask_living" and state.get("nursing_home") is not None:
        return True
    if step == "ask_other_coverage" and state.get("other_coverage") is not None:
        return True
    if step == "soa" and state.get("soa_agreed") is True:
        return True
    if step == "ask_decision_maker" and state.get("decision_maker") is True:
        return True
    return False


def resolve_next_step(step: str, state: dict[str, Any]) -> str:
    """Advance, skipping steps already satisfied by caller dumps."""
    nxt = next_after(step, state)
    guard = 0
    while nxt not in ("done", "plan_review", "dual_attestation", "plan_confirm", "address", "enrollment_readback", "voice_signature", "close_success") and step_already_satisfied(nxt, state) and guard < 12:
        if nxt == "ask_other_coverage" and state.get("other_coverage") == "employer":
            return "ask_other_coverage"  # handle terminal there
        step = nxt
        nxt = next_after(step, state)
        guard += 1
    return nxt


def state_is_not_dm(state: dict[str, Any], text: str) -> bool:
    if state.get("decision_maker") is False:
        return True
    t = _lower(text)
    if _has_any(t, ["daughter", "son handles", "someone else makes", "my kids"]):
        if not _has_any(t, ["i make", "my own"]):
            return True
    if _has_any(t, ["no, my", "no my"]) and _has_any(t, ["daughter", "son", "husband", "wife"]):
        return True
    return False


def assemble_response(directive: Directive, message: str) -> dict[str, Any]:
    msg = (message or "").strip()
    if not msg:
        msg = "Thanks — let me ask you this next."
    # Strip accidental JSON / labels
    if msg.startswith("{") and "message" in msg:
        try:
            import json

            obj = json.loads(msg[msg.find("{") : msg.rfind("}") + 1])
            if isinstance(obj.get("message"), str):
                msg = obj["message"].strip()
        except Exception:  # noqa: BLE001
            pass
    return {
        "message": msg,
        "state": directive.state,
        "next": directive.next,
        "action": directive.action,
    }
