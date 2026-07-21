"""Intelligent reply classification for the Medicare closer controller.

Every caller utterance is classified before the flow advances:
  answer | question | objection | gibberish | unclear | tangent
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

ReplyKind = Literal[
    "answer",
    "question",
    "objection",
    "gibberish",
    "unclear",
    "tangent",
    "empty",
]


@dataclass
class ReplyAnalysis:
    kind: ReplyKind
    answered: bool
    reason: str
    speech_prefix: str = ""
    emotion: str = "warm"


def _lower(text: str) -> str:
    return (text or "").strip().lower()


def _collapse_repeats(text: str) -> str:
    """suuuuure → sure, yesss → yes (typo / drawn-out speech)."""
    return re.sub(r"(.)\1{1,}", r"\1", (text or "").lower())


def _normalize_tokens(text: str) -> str:
    t = _lower(text)
    t = re.sub(r"[^a-z0-9\s'\-?]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _has_any(text: str, needles: list[str]) -> bool:
    t = _lower(text)
    return any(n.lower() in t for n in needles)


def _yes(text: str) -> bool:
    t = _normalize_tokens(text)
    collapsed = _collapse_repeats(t)
    # Typo fixes: suure/suer/shure → sure
    collapsed = collapsed.replace("suure", "sure").replace("suer", "sure").replace("shure", "sure")
    collapsed = re.sub(r"\bs+u+r+e+\b", "sure", collapsed)
    if collapsed in {
        "y",
        "ye",
        "yes",
        "yea",
        "yeah",
        "yep",
        "yap",
        "sure",
        "ok",
        "okay",
        "k",
        "fine",
        "alright",
        "si",
        "sí",
    }:
        return True
    raw = re.sub(r"[^a-z]", "", t)
    raw_c = _collapse_repeats(raw)
    if raw_c in {"sure", "yes", "yeah", "yep", "ok", "okay"} or re.fullmatch(r"s+u+r+e+", raw):
        return True
    if _has_any(
        t,
        [
            "yes",
            "yeah",
            "yep",
            "sure",
            "okay",
            "ok",
            "i agree",
            "sounds good",
            "go ahead",
            "correct",
            "that's right",
            "please do",
            "i guess",
            "alright",
            "all right",
        ],
    ):
        return True
    return False


def _no(text: str) -> bool:
    t = _lower(text)
    # "none" means zero/nothing (conditions/meds) — NOT a yes/no "no"
    if t in {"none", "nothing", "n/a", "na"}:
        return False
    return t in {"no", "nope", "nah"} or _has_any(
        t, ["no,", "no.", "not really", "don't", "do not", "never"]
    )


def is_gibberish(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # Drawn-out yes/sure/no/ok are NOT gibberish
    if _yes(t) or _no(t):
        return False
    collapsed = _collapse_repeats(t.lower())
    if collapsed in {"sure", "yes", "yeah", "yep", "ok", "okay", "no", "nope", "nah"}:
        return False
    if re.fullmatch(r"s+u+r+e+", re.sub(r"[^a-z]", "", t.lower())):
        return False
    letters = re.sub(r"[^a-zA-Z]", "", t)
    if len(t) >= 6 and letters:
        vowels = sum(1 for c in letters.lower() if c in "aeiou")
        if vowels == 0 and len(letters) >= 4:
            return True
    # Repeated chars only count as gibberish if it's not an affirmation skeleton
    if re.search(r"(.)\1{4,}", t.lower()):
        skeleton = _collapse_repeats(re.sub(r"[^a-z]", "", t.lower()))
        if skeleton not in {"sure", "yes", "yeah", "ok", "okay", "no", "nope", "hi", "hey"}:
            return True
    if re.fullmatch(r"[^\w\s]+", t):
        return True
    if _has_any(t.lower(), ["asdf", "qwer", "zxcv", "lorem", "blah blah", "ajsd"]):
        return True
    tokens = t.split()
    if len(tokens) == 1 and len(tokens[0]) > 12 and vowels_ratio(tokens[0]) < 0.15:
        return True
    return False


def vowels_ratio(word: str) -> float:
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0.0
    return sum(1 for c in w if c in "aeiou") / len(w)


def is_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "?" in t:
        return True
    tl = t.lower()
    if re.match(
        r"^(what|why|how|when|where|who|which|can you|could you|do you|are you|is that|is this|will you|would you|whats|where's|wheres)\b",
        tl,
    ):
        return True
    if _has_any(
        tl,
        [
            "what does that mean",
            "what do you mean",
            "what is ",
            "what's ",
            "whats ",
            "explain",
            "tell me more",
            "how much",
            "how does",
            "why would",
            "is that free",
            "does that include",
            "who are you",
            "last name",
            "where is your",
            "where are you",
            "located",
            "company",
        ],
    ):
        return True
    return False


def _is_pure_question(text: str) -> bool:
    """True when the utterance is asking, not answering with a side question."""
    t = _lower(text)
    # Multi-fact dumps that happen to include a question ("…is there anything better?")
    if len(t.split()) > 10 and _has_any(
        t,
        [
            "no chronic",
            "no meds",
            "no other",
            "no coverage",
            "i have",
            "i make",
            "live at home",
            "i'm happy",
            "im happy",
        ],
    ):
        return False
    if re.match(
        r"^(hi|hello|hey)?\s*(what|why|how|when|where|who|which|whats|where's)\b",
        t,
    ):
        return True
    if _has_any(t, ["who are you", "last name", "where is your", "where are you", "located"]):
        return True
    if _has_any(t, ["what is ", "what's ", "whats ", "what does", "explain"]) and not _has_any(
        t, ["i have", "yes i", "no i don't", "i do have"]
    ):
        return True
    if "?" in text and not _yes(text) and not _has_any(t, ["i have", "i don't have"]) and len(t.split()) < 12:
        return True
    return False


def _clarify_guidance(step: str, kind: str, text: str = "") -> str:
    """Warm, specific re-ask — never a flat 'I didn't catch that'."""
    examples = {
        "intro": 'Ask if now is a good time — e.g. "Sure, go ahead" or "Can you call later?"',
        "disclaimers": 'Ask them to confirm continuing — e.g. "Yes, I agree" or "Sure."',
        "soa": 'Ask for a clear yes to continue the appointment — e.g. "Yes, I agree."',
        "ask_decision_maker": 'Ask if they make their own healthcare decisions — e.g. "Yes, I do" or "My daughter helps."',
        "ask_callback": 'Ask if you may call back on this number if the line drops — "Yes" or "No" is enough.',
        "ask_satisfaction": 'Ask how they like their current plan — e.g. "I like it" or "It\'s been okay" or "Not great."',
        "ask_conditions": 'Ask about diabetes, blood clots, or stroke — e.g. "No" / "None" / "Yes, diabetes."',
        "ask_doctor": 'Ask how often they see a doctor — e.g. "Every few months" / "Rarely" / "I went yesterday."',
        "ask_meds": 'Ask about regular medications — e.g. "None" / "Yes, two blood pressure meds" / "Just insulin."',
        "ask_priorities": 'Ask what matters most — e.g. "Low cost" / "Dental" / "Extra benefits."',
        "ask_living": 'Ask if they live at home or in a nursing/long-term care facility — "At home" or "In a facility."',
        "ask_other_coverage": 'Ask about employer, VA, or TRICARE — e.g. "No" / "I have VA" / "Through work."',
        "plan_review": "Ask how the plan sounds — e.g. \"Sounds good\" or \"Too expensive\" or \"Tell me more.\"",
        "plan_confirm": 'Ask for a clear yes to enroll — "Yes" or "No."',
        "address": 'Ask for their street address — e.g. "123 Main Street, Springfield."',
        "enrollment_readback": 'Ask if they agree with the enrollment disclosures — "Yes, I agree."',
        "voice_signature": 'Ask for full name, date of birth, today\'s date, and "I agree."',
    }
    tip = examples.get(step, "Re-ask the current question with one short example answer.")
    if kind == "empty":
        return (
            f"They were silent. Warmly check in: 'Are you still with me?' Then {tip} "
        )
    if kind == "gibberish":
        return (
            f"Audio was garbled. Say: 'I want to make sure I heard you right' — then {tip} "
        )
    # unclear
    heard = (text or "").strip()
    bit = (
        f'They said something like "{heard[:40]}". If those were real words, acknowledge them. '
        if heard and len(heard) > 1
        else ""
    )
    return (
        f"{bit}It may not fully answer the question. Give one short acknowledgment, then {tip} "
    )


def _question_guidance(step: str, text: str) -> str:
    """Specific coaching so the LLM actually answers the caller's question."""
    t = _lower(text)
    if _has_any(t, ["last name", "surname", "full name"]):
        return (
            "They asked your last name. Answer naturally: your full name is Alex Rivera "
            "(licensed agent). Then gently return to the current question. "
        )
    if _has_any(t, ["who are you", "who is this", "speaking with"]):
        return (
            "They asked who you are. Re-introduce briefly: Alex Rivera, licensed Medicare agent "
            "with Summit Senior Advisors. Then ask if now is still a good time / the current question. "
        )
    if _has_any(t, ["nearest", "near me", "closest", "nearset", "newarsest"]) and _has_any(
        t, ["facility", "nursing", "care", "home"]
    ):
        return (
            "They asked where the nearest long-term care facility is. Be honest: you don't look up "
            "facility directories on this call. Clarify you're only asking whether THEY currently live "
            "at home or already live in a nursing/long-term care facility — yes/no style. "
            "Do NOT skip to another topic. Do NOT say you didn't catch that. "
        )
    if _has_any(t, ["where", "located", "location", "company", "office"]) and not _has_any(
        t, ["facility", "nursing", "nearest"]
    ):
        return (
            "They asked where the company is. Answer: Summit Senior Advisors is based in Texas. "
            "Then return to the current question only. "
        )
    if _has_any(t, ["diabetes"]) and _has_any(t, ["what", "mean", "explain", "?"]):
        return (
            "They asked what diabetes is — NOT saying they have it. Give a one-sentence plain-English "
            "explanation (blood sugar condition). Then re-ask whether THEY have diabetes, blood clots, "
            "or a stroke history. Do NOT skip ahead. Do NOT assume they have diabetes. "
        )
    return (
        "They asked a question. Answer it briefly and clearly in 1 sentence, "
        "using only accurate info — then politely re-ask the CURRENT question so we can continue. "
        "Do NOT advance to a new topic. Never say 'I didn't quite catch that' when they asked something clear. "
    )


def is_objection(text: str, step: str) -> bool:
    t = _lower(text)
    if _has_any(
        t,
        [
            "expensive",
            "too much",
            "can't afford",
            "cannot afford",
            "costs too",
            "too pricey",
            "cheaper",
            "not sure",
            "i don't know",
            "dont know",
            "hesitant",
            "think about it",
            "let me think",
            "maybe later",
            "not interested in that",
            "don't like that",
            "something else",
            "other option",
            "different plan",
        ],
    ):
        return True
    if step in ("plan_review", "plan_confirm") and _has_any(
        t, ["looks bad", "not for me", "no thanks", "pass"]
    ):
        return True
    return False


def step_answered(step: str, text: str, state: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, reason). Stricter than old heuristics."""
    t = _lower(text)
    if not t:
        return False, "empty"

    if step in ("intro",):
        if _yes(t) or _has_any(t, ["go ahead", "talk", "listen", "now is fine", "good time"]):
            return True, "willing_to_talk"
        return False, "no_clear_consent"

    if step in ("disclaimers", "soa"):
        if re.search(r"\bagree\b", t) or _has_any(t, ["continue", "soa", "appointment", "recorded"]):
            return True, "soa_accept"
        if _yes(t):
            return True, "soft_yes"
        return False, "need_soa_yes"

    if step == "ask_decision_maker":
        if _has_any(
            t,
            [
                "make my own",
                "i make",
                "i decide",
                "my own",
                "most of the time",
                "usually i",
                "i do",
            ],
        ) or (_yes(t) and not _has_any(t, ["daughter", "son", "someone else"])):
            return True, "is_dm"
        if _has_any(t, ["daughter", "son", "someone else", "my kids", "husband", "wife", "power of attorney"]):
            return True, "not_dm"
        return False, "unclear_dm"

    if step == "ask_callback":
        if t in {"none", "nothing"}:
            return False, "need_callback_yes_no"
        if _yes(t) or _has_any(t, ["this number", "same number", "call me", "callback"]):
            return True, "callback_ok"
        if t in {"no", "nope", "nah"} or _has_any(t, ["don't call", "do not call", "no callback"]):
            return True, "callback_no"
        return False, "need_callback_yes_no"

    if step == "ask_satisfaction":
        if _has_any(
            t,
            [
                "fine",
                "good",
                "great",
                "okay",
                "ok",
                "love",
                "like",
                "happy",
                "hate",
                "not good",
                "bad",
                "terrible",
                "awful",
                "so-so",
                "meh",
                "humana",
                "aetna",
                "united",
                "cigna",
                "plan",
                "expensive",
                "works",
                "doesn't work",
                "dont work",
            ],
        ):
            return True, "satisfaction_given"
        return False, "need_plan_opinion"

    if step == "ask_conditions":
        if t in {"none", "no", "nope", "nothing", "nah"} or _has_any(
            t, ["no chronic", "no diabetes", "none of those", "healthy", "no conditions", "nothing like"]
        ):
            return True, "no_conditions"
        if _has_any(t, ["diabetes", "diabetic", "stroke", "clot", "heart"]):
            return True, "has_condition"
        return False, "need_conditions"

    if step == "ask_doctor":
        if t in {"monthly", "weekly", "yearly", "rarely", "never", "seldom", "often", "sometimes"}:
            return True, "frequency"
        if _has_any(
            t,
            [
                "doctor",
                "pcp",
                "dr",
                "every month",
                "once a",
                "few times",
                "don't go",
                "do not go",
                "not often",
                "regularly",
                "month",
                "year",
                "week",
                "yesterday",
                "today",
                "last week",
                "last month",
                "went to",
                "i did go",
                "i go",
                "checkup",
                "check up",
                "visit",
            ],
        ):
            return True, "doctor_info"
        if re.search(r"\d+", t) and _has_any(t, ["time", "visit", "month", "year"]):
            return True, "doctor_count"
        return False, "need_doctor_frequency"

    if step == "ask_meds":
        if t.isdigit() or re.fullmatch(r"\d+\s*(meds?|medications?)?", t):
            return True, "med_count"
        if t in {"none", "no", "nope", "nothing", "zero"} or _has_any(
            t, ["no med", "not on any", "don't take", "no prescription"]
        ):
            return True, "no_meds"
        # "i am" / "yes I am" = yes on meds (details optional)
        if re.match(r"^(i am|i'm|im|yes i am|yeah i am)\b", t) or (
            _yes(t) and len(t.split()) <= 3 and not _has_any(t, ["not", "no"])
        ):
            return True, "meds_affirm"
        if _has_any(t, ["med", "prescription", "blood pressure", "pill", "insulin", "just "]):
            return True, "meds_named"
        return False, "need_meds"

    if step == "ask_priorities":
        if _has_any(
            t,
            [
                "cost",
                "cheap",
                "afford",
                "dental",
                "vision",
                "food",
                "otc",
                "cash",
                "giveback",
                "doctor",
                "network",
                "everything",
                "all",
                "benefits",
                "low",
                "premium",
                "whatever",
                "best",
            ],
        ):
            return True, "priorities"
        return False, "need_priorities"

    if step == "ask_living":
        # Asking where a facility is ≠ saying they live in one
        if _has_any(t, ["where", "nearest", "near me", "closest", "which", "find", "newarsest", "nearset"]):
            return False, "living_question"
        if _has_any(t, ["nursing", "facility", "long-term", "long term", "assisted"]):
            return True, "facility"
        if _has_any(t, ["home", "apartment", "condo", "house", "live alone", "with family"]):
            return True, "home"
        if t in {"nursing", "home", "facility"}:
            return True, "living_short"
        return False, "need_living"

    if step == "ask_other_coverage":
        if t in {"no", "nope", "none", "nah", "nothing"} or _has_any(
            t, ["no other", "no employer", "no coverage", "don't have", "do not have"]
        ):
            return True, "no_other"
        if _has_any(t, ["employer", "job", "work", "retiree", "va", "tricare", "veteran"]):
            return True, "has_other"
        return False, "need_coverage_answer"

    if step == "plan_review":
        if is_objection(text, step):
            return False, "objection"
        if _yes(t) or _has_any(
            t,
            [
                "sounds good",
                "sounds better",
                "let's",
                "lets",
                "do it",
                "enroll",
                "that one",
                "otc one",
                "this one",
                "interested",
                "love it",
                "go with",
                "I'll take",
                "ill take",
            ],
        ):
            return True, "accept_plan"
        if _no(t) or _has_any(t, ["stay", "keep current", "not interested"]):
            return True, "decline_plan"
        return False, "need_plan_reaction"

    if step == "dual_attestation":
        if _has_any(t, ["attest", "diabetes", "doctor", "dr", "555", "phone", "seen"]):
            return True, "attestation"
        if re.search(r"\d{3}", text):
            return True, "pcp_phone"
        return False, "need_attestation"

    if step == "plan_confirm":
        if is_objection(text, step):
            return False, "objection"
        # Caller jumped ahead with street address
        if re.search(r"\d+\s+\w+", text) and _has_any(
            t, ["street", "ave", "road", "blvd", "lane", "drive", "main", "oak", "springfield"]
        ):
            return True, "gave_address"
        if _yes(t) or _has_any(t, ["agree", "correct", "enroll", "go ahead"]):
            return True, "confirm"
        if _no(t):
            return True, "reject_confirm"
        return False, "need_confirm"

    if step == "address":
        # Require something address-like — not name/DOB dumps
        if re.search(r"\d+\s+\w+", text):
            return True, "street_address"
        if _has_any(
            t,
            [
                "street",
                "ave",
                "avenue",
                "road",
                "blvd",
                "lane",
                "drive",
                "apt",
                "suite",
                "new york",
                "downtown",
                "springfield",
            ],
        ) and len(t.split()) >= 2:
            return True, "place_address"
        if re.search(r"\d{5}", text):  # zip
            return True, "zip_address"
        return False, "need_address"

    if step == "enrollment_readback":
        if _yes(t) or _has_any(t, ["agree", "correct", "understood"]):
            return True, "readback_ok"
        return False, "need_readback_yes"

    if step == "voice_signature":
        has_agree = bool(re.search(r"\bagree\b", t))
        has_year = bool(re.search(r"\d{4}", text))
        has_name = bool(re.search(r"[A-Za-z]{2,}", text)) and len(t.split()) >= 2
        if has_agree and (has_year or has_name):
            return True, "voice_sig"
        if has_agree and re.search(r"\d", text):
            return True, "voice_sig_loose"
        return False, "need_full_voice_sig"

    return _yes(t) or len(t.split()) >= 2, "generic"


def commit_step_answer(step: str, text: str, state: dict[str, Any]) -> None:
    """Persist facts from a validated answer into state."""
    t = _lower(text)
    flags = state.setdefault(
        "flags",
        {"dnc": False, "abuse": False, "side_topic": False, "medicaid_dual": False},
    )

    if step == "ask_decision_maker":
        if _has_any(t, ["daughter", "son", "someone else", "my kids", "husband", "wife"]):
            if not _has_any(t, ["i make", "my own", "most of the time"]):
                state["decision_maker"] = False
                return
        state["decision_maker"] = True

    if step == "ask_callback":
        state["callback_ok"] = not (_no(t) and not _yes(t))
        if _yes(t):
            state["callback_ok"] = True
        if _no(t) and not _yes(t):
            state["callback_ok"] = False

    if step == "ask_satisfaction":
        if _has_any(t, ["not good", "bad", "hate", "terrible", "awful", "expensive"]):
            state["plan_satisfaction"] = "poor"
        elif _has_any(t, ["fine", "good", "great", "love", "like", "happy", "okay", "ok"]):
            state["plan_satisfaction"] = "ok"
        else:
            state["plan_satisfaction"] = "mixed"
        for plan in ("humana", "aetna", "united", "cigna", "anthem", "wellcare"):
            if plan in t:
                state["current_plan"] = plan.title() if plan != "united" else "United"

    if step == "ask_conditions":
        if t in {"none", "no", "nope", "nothing", "nah"} or _has_any(
            t, ["no chronic", "no diabetes", "none of", "healthy", "no conditions"]
        ):
            if not _has_any(t, ["diabetes", "diabetic", "stroke"]):
                state["conditions"] = ["none"]
                return
        conds = [c for c in (state.get("conditions") or []) if c != "none"]
        for c in ("diabetes", "stroke", "blood clot", "heart failure"):
            if c.split()[0] in t or c in t:
                label = "diabetes" if "diabet" in c else c
                if label == "diabetes" and "diabet" in t:
                    label = "diabetes"
                if "diabet" in t and "diabetes" not in conds:
                    conds.append("diabetes")
                elif c in t and c not in conds:
                    conds.append(c)
        if "diabet" in t and "diabetes" not in conds:
            conds.append("diabetes")
        if "stroke" in t and "stroke" not in conds:
            conds.append("stroke")
        if "clot" in t and "blood clot" not in conds:
            conds.append("blood clot")
        state["conditions"] = conds or ["none"]

    if step == "ask_doctor":
        state["doctor"] = text.strip()[:120]

    if step == "ask_meds":
        if t.isdigit():
            state["meds"] = f"{t} medications"
        elif t in {"none", "no", "nope", "zero", "nothing"}:
            state["meds"] = "none"
        elif re.match(r"^(i am|i'm|im|yes i am|yeah i am)\b", t) or (
            _yes(t) and len(t.split()) <= 3
        ):
            state["meds"] = "yes (unspecified)"
        else:
            state["meds"] = text.strip()[:120]

    if step == "ask_priorities":
        if _has_any(t, ["food"]):
            state["priorities"] = "food card"
            flags["medicaid_dual"] = True
        elif _has_any(t, ["cost", "cheap", "afford", "otc", "low", "premium"]):
            state["priorities"] = "low cost"
        elif _has_any(t, ["everything", "all", "benefits"]):
            state["priorities"] = "comprehensive benefits"
        elif _has_any(t, ["dental", "vision"]):
            state["priorities"] = "dental/vision"
        elif _has_any(t, ["network", "doctor"]):
            state["priorities"] = "network/doctors"
        else:
            state["priorities"] = text.strip()[:80]

    if step == "ask_living":
        if _has_any(t, ["nursing", "facility", "long-term", "long term", "assisted"]):
            state["nursing_home"] = True
        else:
            state["nursing_home"] = False

    if step == "ask_other_coverage":
        if t in {"no", "nope", "none", "nah", "nothing"} or _has_any(
            t, ["no other", "no employer", "no coverage", "don't have"]
        ):
            state["other_coverage"] = "none"
        elif _has_any(t, ["employer", "job", "work", "retiree"]):
            state["other_coverage"] = "employer"
        elif "tricare" in t:
            state["other_coverage"] = "tricare"
        elif re.search(r"\bva\b", t) or "veteran" in t:
            state["other_coverage"] = "va"

    if step == "address":
        state["address"] = text.strip()[:160]

    if step == "voice_signature":
        state["voice_signed"] = True
        # first token-ish name
        parts = text.strip().split(",")[0].split()
        if parts:
            state["caller_name"] = parts[0].strip().title()


def analyze_reply(step: str, text: str, state: dict[str, Any]) -> ReplyAnalysis:
    """Classify the caller utterance relative to the current step."""
    raw = (text or "").strip()
    if not raw:
        return ReplyAnalysis(
            kind="empty",
            answered=False,
            reason="empty",
            speech_prefix=_clarify_guidance(step, "empty"),
            emotion="patient",
        )

    if is_gibberish(raw):
        return ReplyAnalysis(
            kind="gibberish",
            answered=False,
            reason="gibberish",
            speech_prefix=_clarify_guidance(step, "gibberish", raw),
            emotion="patient",
        )

    # Questions first — asking "what is diabetes?" is NOT saying they have diabetes
    if is_question(raw) or _has_any(
        raw, ["nearest", "newarsest", "nearset", "closest", "where is my", "where’s my"]
    ):
        pure = _is_pure_question(raw) or _has_any(
            raw, ["nearest", "newarsest", "where is my", "closest", "what is"]
        )
        if pure:
            return ReplyAnalysis(
                kind="question",
                answered=False,
                reason="user_question",
                speech_prefix=_question_guidance(step, raw),
                emotion="helpful",
            )
        ok, reason = step_answered(step, raw, state)
        if ok and (_yes(raw) or _no(raw) or _has_any(raw, ["i have", "i don't", "i do not"])):
            return ReplyAnalysis(kind="answer", answered=True, reason=reason)
        return ReplyAnalysis(
            kind="question",
            answered=False,
            reason="user_question",
            speech_prefix=_question_guidance(step, raw),
            emotion="helpful",
        )

    if is_objection(raw, step) and step in (
        "plan_review",
        "plan_confirm",
        "enrollment_readback",
    ):
        return ReplyAnalysis(
            kind="objection",
            answered=False,
            reason="objection",
            speech_prefix=_objection_guidance(step, raw, state),
            emotion="understanding",
        )

    ok, reason = step_answered(step, raw, state)
    if ok:
        return ReplyAnalysis(kind="answer", answered=True, reason=reason)

    # Long unrelated tangent
    if len(raw.split()) > 14 and not ok:
        return ReplyAnalysis(
            kind="tangent",
            answered=False,
            reason="tangent",
            speech_prefix=(
                "Acknowledge what they shared in one warm clause, then gently return "
                "to ONLY the current question with a simple example answer. "
                "Do not say 'I didn't quite catch that.' "
            ),
            emotion="empathetic",
        )

    return ReplyAnalysis(
        kind="unclear",
        answered=False,
        reason=reason,
        speech_prefix=_clarify_guidance(step, "unclear", raw),
        emotion="patient",
    )


def _objection_guidance(step: str, text: str, state: dict[str, Any]) -> str:
    t = _lower(text)
    if _has_any(t, ["expensive", "cost", "afford", "cheaper", "pricey"]):
        state["priorities"] = "low cost"
        # Prefer switching catalog plan toward OTC on cost objection
        if state.get("soa_agreed"):
            flags = state.get("flags") or {}
            if not flags.get("medicaid_dual"):
                state["selected_plan_id"] = "otc_zero"
        return (
            "They think the plan sounds expensive. Empathize. Clarify the premium is $0 for "
            "the OTC option if switching, or explain GiveBack reduces Part B cost. "
            "Offer the Summit Care Zero OTC ($0 premium, $44 OTC card) as a lower-cost alternative, "
            "ask which they prefer — do NOT push enrollment yet. "
        )
    if _has_any(t, ["think about", "not sure", "maybe later"]):
        return (
            "They're hesitant. No pressure — offer to answer one concern or schedule a callback. "
            "Stay on this step; do not enroll. "
        )
    return (
        "They objected. Acknowledge the concern, address it briefly, then ask if they want "
        "another option or to continue — do not enroll yet. "
    )


def forward_fact_dump(text: str, state: dict[str, Any]) -> bool:
    """True if utterance clearly supplies later-step facts (caller answering ahead)."""
    t = _lower(text)
    if _has_any(
        t,
        [
            "no employer",
            "no other coverage",
            "food card",
            "food and utility",
            "let's enroll",
            "lets enroll",
        ],
    ):
        return True
    if _has_any(t, ["live at home", "nursing"]) and _has_any(
        t, ["coverage", "employer", "va", "no other", "work"]
    ):
        return True
    if _has_any(t, ["diabetes", "dual eligible"]) and _has_any(t, ["food", "enroll", "attest"]):
        return True
    return False


def absorb_forward_dump(text: str, state: dict[str, Any]) -> None:
    """Commit ahead-of-time facts from a multi-answer dump."""
    t = _lower(text)
    flags = state.setdefault(
        "flags",
        {"dnc": False, "abuse": False, "side_topic": False, "medicaid_dual": False},
    )
    if _has_any(t, ["no employer", "no other coverage", "no coverage through"]) or (
        _has_any(t, ["nope", "no"]) and _has_any(t, ["employer", "coverage", "va", "work"])
    ):
        if not _has_any(t, ["still have", "kept me on"]):
            state["other_coverage"] = "none"
    if _has_any(t, ["food card", "food and utility"]):
        state["priorities"] = "food card"
        flags["medicaid_dual"] = True
        if state.get("soa_agreed"):
            state["selected_plan_id"] = "dual_food_snp"
    if _has_any(t, ["live at home", "own home"]):
        state["nursing_home"] = False
    if _has_any(t, ["nursing"]):
        state["nursing_home"] = True
    if _has_any(t, ["diabetes", "diabetic"]):
        conds = [c for c in (state.get("conditions") or []) if c != "none"]
        if "diabetes" not in conds:
            conds.append("diabetes")
        state["conditions"] = conds
    if _has_any(t, ["doesn't cost", "low cost", "cheap", "otc"]):
        state["priorities"] = state.get("priorities") or "low cost"
