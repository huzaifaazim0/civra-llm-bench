"""Fixed fake Medicare Advantage plan catalog for the closer agent."""

from __future__ import annotations

from typing import Any

PLANS: list[dict[str, Any]] = [
    {
        "id": "giveback_ppo",
        "name": "Summit GiveBack PPO",
        "type": "Part B giveback PPO",
        "premium": "$0",
        "headline": "$103 monthly Part B premium reduction credited to Social Security",
        "benefits": [
            "$103 Part B giveback",
            "Standard dental and vision",
            "PPO — out-of-network allowed at higher copay",
            "Prescription drug coverage included",
        ],
        "best_for": "Callers without Medicaid who want Part B giveback and network flexibility",
        "requires_dual": False,
        "requires_chronic_attestation": False,
    },
    {
        "id": "otc_zero",
        "name": "Summit Care Zero OTC",
        "type": "MAPD",
        "premium": "$0",
        "headline": "$44 monthly over-the-counter allowance (Walmart / Walgreens)",
        "benefits": [
            "$0 plan premium",
            "$44 OTC card",
            "Diabetes-friendly formulary",
            "Standard dental and vision",
        ],
        "best_for": "Cost-focused callers, especially with diabetes or blood-pressure meds",
        "requires_dual": False,
        "requires_chronic_attestation": False,
    },
    {
        "id": "dual_food_snp",
        "name": "Summit Dual Food C-SNP",
        "type": "Dual C-SNP",
        "premium": "$0",
        "headline": "Monthly food and utility U-card (not Part B giveback)",
        "benefits": [
            "Food and utility spending allowance via U-card",
            "Extra dental and vision for dual eligibles",
            "Chronic condition Special Needs Plan",
            "No Part B giveback (Medicaid pays Part B)",
        ],
        "best_for": "Medicaid dual-eligible callers with a qualifying chronic condition",
        "requires_dual": True,
        "requires_chronic_attestation": True,
    },
]

PLAN_BY_ID = {p["id"]: p for p in PLANS}
PLAN_IDS = tuple(p["id"] for p in PLANS)

DEFAULT_EFFECTIVE_DATE = "January 1, 2026"
PLAN_YEAR = "2026"


def catalog_for_prompt() -> str:
    """Human-readable catalog injected into the system prompt."""
    lines = ["Available plans (you MUST pick only from these IDs):"]
    for p in PLANS:
        lines.append(
            f"- id=`{p['id']}` | {p['name']} ({p['type']}) | premium {p['premium']} | "
            f"{p['headline']} | best_for: {p['best_for']}"
        )
        lines.append(f"  benefits: {'; '.join(p['benefits'])}")
    lines.append(
        "Selection rules: medicaid_dual=true → prefer dual_food_snp; "
        "cost focus + chronic (diabetes/stroke/clot) without dual → prefer otc_zero; "
        "no medicaid + wants cash back / giveback → prefer giveback_ppo."
    )
    return "\n".join(lines)
