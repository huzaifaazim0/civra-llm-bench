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

# Freeform transcript — `employer_conflict`

**Description:** Employer coverage → close_employer_conflict  
**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T15:31:52.379838+00:00  

---

### Turn 0

**Caller:** (opening)

**Agent:** Hello, this is Alex from Summit Senior Advisors. I hope you're doing well. Today, I'd like to review your Medicare plans for the upcoming plan year starting January 1, 2026. Can you hear me clearly?

### Turn 1

**Caller:** Sure.

**Agent:** Great, thank you. Before we proceed, can I record this call for my records? Also, just to remind you, the information we discuss today is subject to availability and may change. Is that okay with you? And do you have someone making decisions about your Medicare coverage?

### Turn 2

**Caller:** Yes I agree to the appointment.

**Agent:** Perfect, thank you for agreeing. Now, let's make sure we have your permission to record this call. Also, just to confirm, there's a decision-maker involved in your Medicare choices. Can I have your zip code, date of birth, and Medicare number to verify your eligibility?

### Turn 3

**Caller:** Yes I make my own decisions.

**Agent:** Okay, great. Can I record this call for my records? And just to confirm, you're the decision-maker for your Medicare coverage. Now, could you please provide your zip code, date of birth, and Medicare number so we can check your eligibility?

### Turn 4

**Caller:** My plan is okay. No diabetes. Rarely see a doctor. No meds. Just low cost.

**Agent:** I understand. Thank you for letting me know. Since your current plan seems to be working well for you and you don't have any diabetes or other chronic conditions, it sounds like you might be a good fit for the Summit GiveBack PPO. It offers a $103 Part B premium reduction, standard dental and vision coverage, and PPO network flexibility. Would you like to learn more about this plan?

### Turn 5

**Caller:** I live at home. Yeah, I still have insurance through my job — retired but they kept me on.

**Agent:** I see, you live at home and you still have insurance through your job. That's great. In that case, since you have employer coverage, it might be best to stick with what you have. Is there anything else you'd like to discuss or any questions you have about your current plan?


