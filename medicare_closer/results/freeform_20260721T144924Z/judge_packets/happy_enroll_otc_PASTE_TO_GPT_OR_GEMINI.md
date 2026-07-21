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

# Freeform transcript — `happy_enroll_otc`

**Description:** Happy path — qualify + enroll otc_zero with voice signature  
**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T14:50:17.877596+00:00  

---

### Turn 0

**Caller:** (opening)

**Agent:** Hello, this is Alex from Summit Senior Advisors. I hope you're doing well. Today, we're going to review your Medicare options for the upcoming plan year starting January 1, 2026. Can I start by asking if you have a moment to discuss your plan?

### Turn 1

**Caller:** Yes, sounds good.

**Agent:** Great! Before we get started, could you please let me know if you're okay with me recording our conversation for quality assurance purposes? Also, just to confirm, are you the decision-maker for your Medicare coverage?

### Turn 2

**Caller:** Yes, I agree to continue.

**Agent:** Thank you, I appreciate that. And yes, you are the decision-maker. For your convenience, may I ask your zip code, date of birth, and if it’s okay, your Medicare number? This will help me find the best plan for you. Also, do you mind if I record this call?

### Turn 3

**Caller:** Yes, I make my own healthcare decisions.

**Agent:** Okay, great. Just to confirm, you make all your healthcare decisions. Now, could you please provide your zip code, date of birth, and Medicare number? This will help me find the best plan for you. Also, can I record this call for quality assurance purposes?

### Turn 4

**Caller:** Yes, you can call me back at this number.

**Agent:** Sure thing. Is it okay if I call you back at this number later to gather your zip code, date of birth, and Medicare number? In the meantime, how satisfied are you with your current Medicare plan?

### Turn 5

**Caller:** Humana has been fine.

**Agent:** That's good to hear that Humana has been working well for you. However, there might be a better option available for you based on your needs. Could you tell me a bit about any health conditions you have, medications you take, and what's most important to you when choosing a Medicare plan? Also, where do you live, and do you have any other types of coverage besides Medicare?

### Turn 6

**Caller:** Yeah, I have diabetes.

**Agent:** Got it, you have diabetes. That's an important factor to consider. Do you also take any other medications regularly? And could you share a little more about your living situation—do you live alone, with family, or somewhere else?

### Turn 7

**Caller:** I don't go to the doctor very often.

**Agent:** That's good to know. Since you don't go to the doctor very often, having a plan with good prescription coverage might be important for you. Could you tell me a bit more about your living situation—do you live alone, with family, or somewhere else? Also, do you have any other types of coverage besides Medicare?

### Turn 8

**Caller:** Just one blood pressure medication.

**Agent:** Okay, just one blood pressure medication. That's great to know. Since you mentioned you don't go to the doctor very often, we can look for a plan that offers good prescription coverage. Could you tell me a bit more about your living situation—do you live alone, with family, or somewhere else? Also, do you have any other types of coverage besides Medicare?

### Turn 9

**Caller:** I want something that doesn't cost too much.

**Agent:** I understand you want something that doesn't cost too much. Based on your needs, I think the Summit Care Zero OTC plan might be a good fit for you. It has a $0 premium and includes a $44 monthly over-the-counter allowance, which could be helpful for managing your diabetes and blood pressure. Would you like to hear more about this plan?

### Turn 10

**Caller:** No, I live at home. No other coverage through work or VA.

**Agent:** Got it, you live at home and don't have any other coverage through work or the VA. The Summit Care Zero OTC plan could be a good choice for you because it has a $0 premium and includes a $44 monthly over-the-counter allowance, which is useful for managing your diabetes and blood pressure. This plan also has a diabetes-friendly formulary. Would you like to review the details of this plan?

### Turn 11

**Caller:** That OTC plan sounds good — let's do it.

**Agent:** Great! Let's go ahead with the Summit Care Zero OTC plan. To confirm, you're okay with the Summit Care Zero OTC plan that has a $0 premium and includes a $44 monthly over-the-counter allowance? This plan also has a diabetes-friendly formulary. Is that correct?

### Turn 12

**Caller:** 123 Main Street, Springfield.

**Agent:** Got it, your address is 123 Main Street, Springfield. Is that correct? I'll make sure to include that in your enrollment information.

### Turn 13

**Caller:** Yes, I agree to all of that.

**Agent:** Perfect, thank you for confirming. You're agreeing to the Summit Care Zero OTC plan with a $0 premium and a $44 monthly over-the-counter allowance. Your plan will start on January 1, 2026. Is there anything else you'd like to add before we finalize this?

### Turn 14

**Caller:** Pat Smith. January 15, 1955. Today is July 21, 2026. I agree.

**Agent:** Thank you, Pat. Your name is Pat Smith, your date of birth is January 15, 1955, and you're agreeing to the plan. Your voice signature is Pat Smith, born January 15, 1955, agreeing to the Summit Care Zero OTC plan starting January 1, 2026. Is everything correct?


