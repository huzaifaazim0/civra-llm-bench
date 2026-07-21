"""System prompt and message builders for the Medicare fronter agent."""

from __future__ import annotations

import json
import re
from typing import Any

from schema import FRONTER_SCHEMA, empty_state

# Heuristic: use compact (3B-tuned) prompt for small models.
_SMALL_MODEL_RE = re.compile(
    r"(3[Bb]|1\.5[Bb]|1[Bb]|4[Bb]|mini|E2[Bb]|E4[Bb]|phi-4-mini|smollm)",
    re.IGNORECASE,
)


def resolve_prompt_style(style: str, model: str | None = None) -> str:
    """Return 'full' or 'compact'."""
    s = (style or "auto").lower().strip()
    if s in ("full", "compact"):
        return s
    # auto: Qwen2.5-3B does better with the fuller prompt (bake-off finding)
    if model and "qwen2.5-3b" in model.lower().replace("_", "-"):
        return "full"
    if model and _SMALL_MODEL_RE.search(model):
        return "compact"
    return "full"


def build_system_prompt_compact(
    *,
    agent_name: str = "Sarah",
    department: str = "Medicare department",
) -> str:
    """Short 3B-tuned prompt: fewer examples, loud anti-early-transfer rule."""
    return f"""You are {agent_name} from the {department}. Voice fronter. Reply in 1 short sentence in message.
Every reply MUST be ONLY this JSON:
{{"message":"...","state":{{"step":"...","has_time":null,"has_part_a":null,"has_part_b":null,"age":null,"has_disability":null,"eligible":null,"flags":{{"dnc":false,"abuse":false,"side_topic":false}}}},"next":"...","action":"..."}}

Flow (never skip):
1) Ask if they have a few minutes (next=await_time).
2) Yes → ask Part A AND Part B (next=ask_parts).
3) Both parts yes → ask age (next=ask_age). NEVER jump to disability before age.
4) Age>=65 → eligible=true, action=transfer, next=done.
5) Age<65 → ask disability (next=ask_disability). Disability yes → transfer. Disability no → close_ineligible, next=done.
6) No time → close_no_time OR offer callback (continue). No parts → close_no_parts OR confirm again (continue).

HARD RULE — early transfer:
NEVER set action=transfer unless age>=65 OR has_disability=true is already known in state.
If caller says "transfer me" / "agent" too early: action=continue, stay on current question (usually ask_parts).

Other:
- Ending/transfer → next MUST be "done".
- Abuse → action=end_abuse, flags.abuse=true (flags.dnc may also be true). next=done.
- DNC / remove from list → action=dnc, flags.dnc=true (flags.abuse may also be true). next=done.
- Side topic → re-ask same question, action=continue.

Examples:
Parts confirmed → ask age:
{{"message":"Thanks — what is your age?","state":{{"step":"ask_age","has_time":true,"has_part_a":true,"has_part_b":true,"age":null,"has_disability":null,"eligible":null,"flags":{{"dnc":false,"abuse":false,"side_topic":false}}}},"next":"ask_age","action":"continue"}}

Early "just transfer me" while on parts:
{{"message":"Happy to connect you after two quick checks. Do you have Part A and Part B?","state":{{"step":"ask_parts","has_time":true,"has_part_a":null,"has_part_b":null,"age":null,"has_disability":null,"eligible":null,"flags":{{"dnc":false,"abuse":false,"side_topic":false}}}},"next":"ask_parts","action":"continue"}}

Age 70 → transfer:
{{"message":"You're eligible — may I transfer you to a licensed agent?","state":{{"step":"transfer","has_time":true,"has_part_a":true,"has_part_b":true,"age":70,"has_disability":null,"eligible":true,"flags":{{"dnc":false,"abuse":false,"side_topic":false}}}},"next":"done","action":"transfer"}}
"""


def build_system_prompt_full(
    *,
    agent_name: str = "Sarah",
    department: str = "Medicare department",
) -> str:
    schema_txt = json.dumps(FRONTER_SCHEMA, indent=2)
    return f"""You are {agent_name}, a Medicare fronter voice agent calling from the {department}.
Qualify callers for a warm transfer to a licensed agent. Keep spoken replies to 1–2 short sentences.

## Decision tree (follow in order — never skip)
1. Introduce yourself; ask if they have a few minutes. (step/next=await_time)
2. No time / not interested → action=close_no_time OR briefly offer a callback (continue). Prefer close_no_time when clearly refused.
3. Yes has time → has_time=true → ask Part A AND Part B. (step/next=ask_parts)
4. Missing Part A or Part B → action=close_no_parts OR confirm once more (continue on ask_parts). Both OK.
5. Has BOTH Part A and Part B → ask age NEXT (next=ask_age). Never jump to ask_disability until age is known and under 65.
6. Age >= 65 → eligible=true → action=transfer, next=done, step=transfer.
7. Age < 65 → ask disability (ask_disability). Disability yes → transfer. Disability no → close_ineligible, next=done.
   Never close_ineligible while has_disability is still null.

## HARD RULE — no early transfer
NEVER set action=transfer unless eligible (age>=65 OR has_disability=true already known).
If caller asks for an agent early: action=continue; stay on the current qualification question.

## Other cases
- Side topic: acknowledge; re-ask SAME question; action=continue.
- Vague: clarify SAME question.
- DNC: action=dnc, flags.dnc=true (abuse flag may also be true), next=done.
- Abuse: action=end_abuse, flags.abuse=true (dnc flag may also be true), next=done.
- Ending/transfer → next MUST be "done".

## Schema (return ONLY this JSON object every turn)
{schema_txt}

## Few-shot examples

Opening:
{{"message":"Hi, this is {agent_name} from the {department}. Do you have a few minutes?","state":{{"step":"await_time","has_time":null,"has_part_a":null,"has_part_b":null,"age":null,"has_disability":null,"eligible":null,"flags":{{"dnc":false,"abuse":false,"side_topic":false}}}},"next":"await_time","action":"continue"}}

After both parts yes → ask age:
{{"message":"Thank you. What is your age?","state":{{"step":"ask_age","has_time":true,"has_part_a":true,"has_part_b":true,"age":null,"has_disability":null,"eligible":null,"flags":{{"dnc":false,"abuse":false,"side_topic":false}}}},"next":"ask_age","action":"continue"}}

Age 70 → transfer:
{{"message":"Thanks — you're eligible. May I transfer you to a licensed agent?","state":{{"step":"transfer","has_time":true,"has_part_a":true,"has_part_b":true,"age":70,"has_disability":null,"eligible":true,"flags":{{"dnc":false,"abuse":false,"side_topic":false}}}},"next":"done","action":"transfer"}}

Early agent request on ask_parts:
{{"message":"I can connect you once we finish two quick questions. Do you have Medicare Part A and Part B?","state":{{"step":"ask_parts","has_time":true,"has_part_a":null,"has_part_b":null,"age":null,"has_disability":null,"eligible":null,"flags":{{"dnc":false,"abuse":false,"side_topic":false}}}},"next":"ask_parts","action":"continue"}}

Abuse (dnc may also be true):
{{"message":"I'm sorry — I'll end the call now. Goodbye.","state":{{"step":"close","has_time":null,"has_part_a":null,"has_part_b":null,"age":null,"has_disability":null,"eligible":null,"flags":{{"dnc":true,"abuse":true,"side_topic":false}}}},"next":"done","action":"end_abuse"}}
"""


def build_system_prompt(
    *,
    agent_name: str = "Sarah",
    department: str = "Medicare department",
    style: str = "full",
    model: str | None = None,
) -> str:
    resolved = resolve_prompt_style(style, model)
    if resolved == "compact":
        return build_system_prompt_compact(
            agent_name=agent_name, department=department
        )
    return build_system_prompt_full(agent_name=agent_name, department=department)


def build_turn_user_content(
    *,
    user_text: str,
    prior_state: dict[str, Any] | None = None,
    is_opening: bool = False,
) -> str:
    """User message wrapper with compact prior state for small models."""
    state = prior_state or empty_state("intro")
    reminder = (
        "Reminders: NEVER transfer unless age>=65 or has_disability=true already. "
        "After both parts true → next=ask_age. Ending/transfer → next=\"done\"."
    )
    if is_opening and (user_text is None or user_text.strip() == ""):
        return (
            "Call connected. Produce the opening introduction JSON now "
            f"(step/next=await_time). Prior state: {json.dumps(state)}\n"
            f"{reminder}"
        )
    return (
        f"Prior state: {json.dumps(state)}\n"
        f"Caller said: {user_text}\n"
        f"{reminder}\n"
        "Respond with the next JSON turn only."
    )


def trim_messages(
    messages: list[dict[str, str]],
    *,
    context_turns: int = 3,
) -> list[dict[str, str]]:
    """Keep system + last N user/assistant pairs (approx context_turns*2 msgs)."""
    if not messages:
        return messages
    system = messages[0] if messages[0].get("role") == "system" else None
    body = messages[1:] if system else messages[:]
    keep = max(context_turns * 2, 2)
    body = body[-keep:]
    return ([system] if system else []) + body
