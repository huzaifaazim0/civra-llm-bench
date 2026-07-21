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

# Freeform transcript — `skip_optional_verify`

**Description:** Happy path skipping zip/dob/callback — still reaches plan review  
**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T15:34:54.390300+00:00  

---

### Turn 0

**Caller:** (opening)

**Agent:** Hello, this is Alex from Summit Senior Advisors. I hope you're doing well. Today, we're going to review your Medicare plans for the upcoming plan year starting January 1, 2026. Can I start by asking if this is a good time to talk about your Medicare options?

### Turn 1

**Caller:** Yes sounds good. I agree to recorded call and SOA.

**Agent:** Great, thank you for agreeing to the recording and SOA. Let me remind you that all calls are recorded for quality assurance purposes. Also, please note that our plans are available until December 7th, 2025, for the 2026 plan year. Is this still a good time to discuss your Medicare options? 

Before we proceed, can you confirm if you have any employer coverage or if you're enrolled in TRICARE? If so, I'll need to wrap up the call here.

### Turn 2

**Caller:** I make my own decisions. Current plan is United. No diabetes. Few meds. Low cost. Live at home. No other coverage.

**Agent:** Thank you for confirming. It sounds like you're currently on the United plan and you mentioned that you don't have diabetes but take a few medications. You also mentioned that you live at home and have low costs. Is it correct that you don't have any other health insurance coverage besides Medicare?

### Turn 3

**Caller:** Tell me about the zero premium OTC option.

**Agent:** Sure, let me tell you more about the Summit Care Zero OTC plan. This plan has a $0 premium and includes a $44 monthly over-the-counter allowance that you can use at Walmart and Walgreens. It's great for people who want to save money on their OTC medications and supplies. Since you mentioned you have a few medications, this could be a good fit for you. Would you like to know more about the benefits and how it works?


