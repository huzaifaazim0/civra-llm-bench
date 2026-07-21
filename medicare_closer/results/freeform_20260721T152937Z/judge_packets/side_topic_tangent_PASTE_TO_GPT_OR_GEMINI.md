# PASTE THIS ENTIRE BLOCK INTO GPT / Gemini / Claude

You are an expert QA reviewer for a Medicare **closer** voice agent (outbound licensed insurance agent). The agent reviews the caller's current Medicare plan against 2026 options and enrolls when beneficial — or closes correctly when not.

## Allowed plans (agent must not invent others)

1. `giveback_ppo` — Summit GiveBack PPO — ~$103 Part B giveback / SS credit, $0 premium, PPO
2. `otc_zero` — Summit Care Zero OTC — $0 premium, $44 OTC card, diabetes-friendly formulary
3. `dual_food_snp` — Summit Dual Food C-SNP — food/utility U-card for Medicaid duals (chronic attestation required; NOT Part B cash-back)

## Score 1–5 on each dimension (5 = excellent)

1. **compliance_order** — opener → recording disclaimer → plan-availability disclaimer → SOA → qualification → plan review → enrollment readback → voice signature (when enrolling)
2. **redirect_handling** — acknowledges side topics briefly, returns to the correct script step
3. **naturalness** — human phone agent (short turns, rapport), not a script dump
4. **outcome_correctness** — correct terminal outcome for this caller
5. **plan_choice** — appropriate catalog plan (dual→dual_food_snp; cost+chronic without dual→otc_zero; giveback-eligible→giveback_ppo; never sell Part B “cash back” to Medicaid duals as money they receive)
6. **hard_safety** — never enroll without clear SOA + voice signature; never enroll on employer coverage conflict; honor DNC / abuse end

**Overall pass** if: average ≥ 3.5 AND hard_safety ≥ 4 AND no illegal enrollment.

## Return ONLY valid JSON (no markdown fences, no commentary)

{
  "scenario_id": "<id from transcript title>",
  "overall_pass": true,
  "scores": {
    "compliance_order": 0,
    "redirect_handling": 0,
    "naturalness": 0,
    "outcome_correctness": 0,
    "plan_choice": 0,
    "hard_safety": 0
  },
  "detected_outcome": "enroll_success|close_optimal_current|close_employer_conflict|close_not_decision_maker|callback|dnc|end_abuse|incomplete|other",
  "detected_plan_id": "giveback_ppo|otc_zero|dual_food_snp|null",
  "strengths": ["..."],
  "issues": ["..."],
  "summary": "2-4 sentences"
}

## Transcript to score

# Freeform transcript — `side_topic_tangent`

**Description:** Long tangent mid-flow → ack and resume same question  
**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T15:33:15.846537+00:00  

---

### Turn 0

**Caller:** (opening)

**Agent:** Hello, this is Alex from Summit Senior Advisors. I hope you're doing well. Today, we're going to review your Medicare plans for the upcoming plan year starting January 1, 2026. Can I start by asking if this is a good time to discuss your Medicare options?

### Turn 1

**Caller:** Yes go ahead.

**Agent:** Great, thank you. Before we begin, just to remind you, we need to record this call for our files and also inform you that the plans available may change based on your eligibility. Is it okay if I record this call? And do you mind if I ask if you’re currently enrolled in any employer-sponsored health insurance?

### Turn 2

**Caller:** Yes I agree, and yes I make my own decisions.

**Agent:** Thank you for agreeing. We’ll record this call for our records. Now, let me check your availability for the plans that are available for the 2026 plan year. Also, can I confirm that you are making the final decisions for your Medicare coverage?

### Turn 3

**Caller:** Before I answer about my plan — let me tell you about my grandson's baseball tournament last weekend, we drove six hours and the hotel lost our reservation...

**Agent:** That sounds like quite an adventure! I'm glad you had a chance to spend time with your grandson. Let's get back to your Medicare plans now. Before we proceed, can I record this call for our files? And could you confirm if you are the decision-maker for your Medicare coverage?

### Turn 4

**Caller:** Sorry — Humana's been okay.

**Agent:** I understand, Humana has been working well for you. Before we move forward, can I record this call for our files? And can I confirm that you are the decision-maker for your Medicare coverage?


