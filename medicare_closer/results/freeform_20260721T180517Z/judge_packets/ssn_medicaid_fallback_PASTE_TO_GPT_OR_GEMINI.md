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

# Freeform transcript — `ssn_medicaid_fallback`

**Description:** Lost Medicare card / Medicaid hesitation → dual food plan path  
**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T18:06:15.015036+00:00  

---

### Turn 0

**Caller:** (opening)

**Agent:** Hello there! I'm Alex, a licensed Medicare insurance agent from Summit Senior Advisors. It's great to talk to you today. Now is this a good time for us to review your current plan and see how it stacks up for 2026?

### Turn 1

**Caller:** Okay, go ahead.

**Agent:** I hear you. Do you usually make your own healthcare decisions, or does someone else help with that?

### Turn 2

**Caller:** Yes I agree.

**Agent:** Great! If the call drops, can I give you a quick call back on this number? No rush, just want to make sure everything goes smoothly.

### Turn 3

**Caller:** Yes I make my own decisions. Humana is okay but I can't find my Medicare card.

**Agent:** I understand about the Medicare card. Have you had any ongoing health issues like diabetes, blood clots, or a stroke that we should consider?

### Turn 4

**Caller:** I don't want to give out my Social Security number.

**Agent:** I completely understand. We can often get the information we need without your Social Security number, or we can wait until you find your Medicare card. Do you see a primary doctor regularly, and how often do you visit? Just curious, no pressure.

### Turn 5

**Caller:** Okay fine — I found my Medicaid card. Yes I'm dual eligible.

**Agent:** That's great to know! Dual eligible members might qualify for extra benefits like food and utility cards through the SNP program. Do you take any regular medications?

### Turn 6

**Caller:** I've never gotten cash back on my plans.

**Agent:** Got it. With Medicaid, the Part B giveback isn't typically available, but dual plans often include food and utility cards, dental coverage, and other extra benefits. What matters most to you in your coverage—cost, dental care, or other extra benefits?

### Turn 7

**Caller:** Diabetes. The food card plan sounds better — let's enroll.

**Agent:** That's fantastic! The food and utility card plan can definitely be a big help. Since you have diabetes, could you please provide me with your primary doctor's name and phone number, and confirm you've seen them within the last two years? This will help us ensure everything is set up correctly for you.

### Turn 8

**Caller:** Dr. Lee, 555-0100. I've seen him this year. I attest to diabetes.

**Agent:** Perfect! You're all set. Would you like to enroll in the Summit Dual Food C-SNP with a premium of $0 starting January 1, 2026? That sounds like a great fit for you.

### Turn 9

**Caller:** 456 Oak Ave. Yes I agree to enroll. Mary Jones, March 3 1948, July 21 2026, I agree.

**Agent:** Great news! You're enrolled in the Summit Dual Food C-SNP with a $0 premium, effective January 1, 2026. You should receive your card in about 3 weeks. Thank you so much for choosing us, Mary! Have a wonderful day ahead.


