# Medicare Fronter Model Bake-off Report

**Stamp:** `20260721T030453Z`  
**Generated:** 2026-07-21T03:30:24.716268+00:00  
**Output dir:** `/root/.cvr/llm_stress_test/medicare_fronter/results/bakeoff_20260721T030453Z`  

## Scoring policy (this run)

- Dual DNC+abuse flags allowed on end_abuse/dnc
- Ask-again OK on no_parts / no_time (continue accepted)
- Early transfer before eligible remains a HARD fail
- Prompt style auto: compact for small models, full for 7B-class

## Correctness leaderboard

| Rank | Model | Pass | Turn OK | Err | Schema | Prompt | TTFT p50/p95 | Gen p50 | TPS |
|-----:|-------|-----:|--------:|----:|-------:|--------|-------------:|--------:|----:|
| 1 | `google/gemma-4-E4B-it` | 12/12 | 1.0 | 0.0 | 1.0 | compact | 84.26/187.37 | 3508.85 | 26.757 |
| 2 | `Qwen/Qwen2.5-7B-Instruct` | 10/12 | 0.9545 | 0.0455 | 1.0 | full | 119.01/276.51 | 6967.67 | 18.364 |
| 3 | `Qwen/Qwen3-4B-Instruct-2507` | 9/12 | 0.9318 | 0.0682 | 1.0 | compact | 70.76/154.8 | 2781.8 | 31.288 |
| 4 | `microsoft/Phi-4-mini-instruct` | 8/12 | 0.9091 | 0.0909 | 1.0 | compact | 66.83/140.74 | 2853.97 | 32.619 |
| 5 | `Qwen/Qwen2.5-3B-Instruct` | 4/12 | 0.7727 | 0.2273 | 1.0 | compact | 56.34/111.99 | 2212.67 | 40.518 |

## Per-model scenario matrix

| Scenario | `gemma-4-e4b` | `qwen2.5-7b` | `qwen3-4b` | `phi-4-mini` | `qwen2.5-3b` |
|----------|------|------|------|------|------|
| `happy_65_plus` | PASS | PASS | PASS | PASS | FAIL |
| `happy_under65_disability` | PASS | FAIL | FAIL | PASS | FAIL |
| `under65_no_disability` | PASS | PASS | FAIL | PASS | FAIL |
| `no_time` | PASS | PASS | PASS | FAIL | PASS |
| `no_parts` | PASS | PASS | FAIL | FAIL | FAIL |
| `side_topic_then_continue` | PASS | PASS | PASS | PASS | PASS |
| `vague_then_clarify` | PASS | PASS | PASS | PASS | PASS |
| `dnc_mid_flow` | PASS | PASS | PASS | PASS | FAIL |
| `abuse_end` | PASS | PASS | PASS | PASS | PASS |
| `partial_parts_clarify` | PASS | FAIL | PASS | FAIL | FAIL |
| `early_transfer_request` | PASS | PASS | PASS | PASS | FAIL |
| `not_interested_as_no_time` | PASS | PASS | PASS | FAIL | FAIL |

## Stress (10c turns / 5c sessions)

| Model | Turns OK | Turns TTFT p95 | Turns TPS | Sess pass | Sess TTFT p95 |
|-------|---------:|---------------:|----------:|----------:|--------------:|
| `gemma-4-e4b` | 1.0 | 379.69 | 24.26 | 1.0 | 525.15 |
| `qwen2.5-7b` | 1.0 | 306.59 | 17.498 | 0.8 | 189.55 |
| `qwen3-4b` | 1.0 | 230.71 | 28.233 | 0.5 | 145.54 |
| `phi-4-mini` | 0.95 | 226.03 | 27.919 | 0.6 | 234.36 |
| `qwen2.5-3b` | 1.0 | 145.18 | 38.506 | 0.4 | 182.41 |

## Failure details (hard fails only)

### `qwen2.5-7b`

- **happy_under65_disability**
  - turn 3: action=`close_ineligible` next=`done` — ["action expected 'continue' got 'close_ineligible'", "next expected 'ask_disability' got 'done'", 'message missing any of [\'disability\', \'disabled\', \'SSDI\', \'Social Security\']: "Thanks — you\'re not yet eligible. Is there something else I can help you with?"']
    - msg: Thanks — you're not yet eligible. Is there something else I can help you with?
- **partial_parts_clarify**
  - turn 2: action=`continue` next=`ask_disability` — ["next expected one of ['ask_parts', 'done'] got 'ask_disability'", "message missing any of ['Part B', 'both', 'Part A', 'thank', 'eligible']: 'I see. Do you have any disability that started before age 65?'"]
    - msg: I see. Do you have any disability that started before age 65?

### `qwen3-4b`

- **happy_under65_disability**
  - turn 3: action=`continue` next=`done` — ["next expected 'ask_disability' got 'done'", 'message missing any of [\'disability\', \'disabled\', \'SSDI\', \'Social Security\']: "You\'re not eligible for Medicare at 58. Would you like to learn more about other coverage options?"']
    - msg: You're not eligible for Medicare at 58. Would you like to learn more about other coverage options?
- **under65_no_disability**
  - turn 4: action=`continue` next=`done` — ["action expected 'close_ineligible' got 'continue'"]
    - msg: Thank you. Since you don't have disability and are under 65, you're not eligible for Medicare. Is there another way I can assist?
- **no_parts**
  - turn 2: action=`continue` next=`await_time` — ["next expected one of ['done', 'ask_parts'] got 'await_time'"]
    - msg: Thanks for letting me know. Would you like to confirm your eligibility or would you like to speak with a representative later?

### `phi-4-mini`

- **no_time**
  - turn 1: action=`end_abuse` next=`done` — ["action expected one of ['close_no_time', 'continue'] got 'end_abuse'"]
    - msg: I understand. We can continue this conversation later when you have more time. Would you like to schedule a callback or should I end our chat for now?
- **no_parts**
  - turn 2: action=`continue` next=`done` — ['action=continue should not have next=done']
    - msg: I understand. Since you don't have Medicare Part A or Part B, you may not be eligible for certain benefits. Would you like to discuss other Medicare options or 
- **partial_parts_clarify**
  - turn 2: action=`continue` next=`ask_age` — ["next expected one of ['ask_parts', 'done'] got 'ask_age'"]
    - msg: Understood. Now, may I know your age to check your eligibility for Medicare Part B?
- **not_interested_as_no_time**
  - turn 1: action=`end_abuse` next=`done` — ["action expected one of ['close_no_time', 'dnc'] got 'end_abuse'"]
    - msg: I understand. If you change your mind in the future, we're here to help. Have a great day!

### `qwen2.5-3b`

- **happy_65_plus**
  - turn 1: action=`continue` next=`ask_parts` — ['state.has_time expected True got None']
    - msg: Great! Do you currently have Part A and/or Part B of Medicare?
- **happy_under65_disability**
  - turn 1: action=`continue` next=`ask_parts` — ['state.has_time expected True got None']
    - msg: Great! Do you currently have Part A and/or Part B of Medicare?
- **under65_no_disability**
  - turn 1: action=`continue` next=`ask_parts` — ['state.has_time expected True got None']
    - msg: Great! Do you have Part A and/or Part B of Medicare?
  - turn 3: action=`continue` next=`close` — ["next expected 'ask_disability' got 'close'"]
    - msg: I'm sorry, but you must be at least 65 years old to qualify for Medicare. Would you like to check your eligibility later or speak with someone else now?
  - turn 4: action=`continue` next=`close` — ["action expected 'close_ineligible' got 'continue'", "next expected 'done' got 'close'", 'state.eligible expected False got None']
    - msg: Okay, since you do not have a disability, you are not eligible for Medicare at this time. Would you like to check your eligibility later or speak with someone e
- **no_parts**
  - turn 2: action=`continue` next=`close` — ["next expected one of ['done', 'ask_parts'] got 'close'", "message missing any of ['thank', 'sorry', 'eligible', 'appreciate', 'Part', 'Medicare', 'confirm', 'have']: 'I see. Is there anything else I can assist you with today?'"]
    - msg: I see. Is there anything else I can assist you with today?
- **dnc_mid_flow**
  - turn 2: action=`end_abuse` next=`done` — ["action expected 'dnc' got 'end_abuse'"]
    - msg: I'm sorry to hear that. Is there something specific I can help with or would you like to remove yourself from our calls?
- **partial_parts_clarify**
  - turn 2: action=`continue` next=`ask_age` — ["next expected one of ['ask_parts', 'done'] got 'ask_age'"]
    - msg: I see. Is there anything else I can assist you with regarding your Medicare Part A?
- **early_transfer_request**
  - turn 2: action=`transfer` next=`done` — ["action expected 'continue' got 'transfer'", "next expected 'ask_parts' got 'done'"]
    - msg: I'm sorry, but we need to verify a few details first. May I proceed with transferring you now?
- **not_interested_as_no_time**
  - turn 1: action=`continue` next=`close` — ["action expected one of ['close_no_time', 'dnc'] got 'continue'", "next expected 'done' got 'close'"]
    - msg: I understand. Is there a specific number where I can reach you if needed?


## Artifacts

- Summary JSON: `/root/.cvr/llm_stress_test/medicare_fronter/results/bakeoff_20260721T030453Z/bakeoff_summary.json`
- Per-model folders under `/root/.cvr/llm_stress_test/medicare_fronter/results/bakeoff_20260721T030453Z/`
- Full console log: `/root/.cvr/llm_stress_test/medicare_fronter/results/bakeoff_20260721T030453Z/bakeoff.log`

## Findings (post-run)

1. **Winner: Gemma-4-E4B** — perfect **12/12** correctness, 100% stress-turn OK, 100% session pass, faster gen than 7B (~3.5s vs ~7s p50).
2. **Qwen2.5-7B** — still strong (**10/12**); residual fails are under-65 disability gate / partial-parts skip (closes or jumps too early).
3. **Qwen3-4B** — best open non-gated small model here (**9/12**); beats Phi-4-mini and Qwen2.5-3B.
4. **Compact prompt hurt Qwen2.5-3B** — auto-compact scored **4/12**; earlier full-prompt run on same model was **9/12**. Prefer `PROMPT_STYLE=full` for Qwen2.5-3B, or switch to Gemma-4-E4B / Qwen3-4B.
5. **Early transfer** — still a hard fail on Qwen2.5-3B only in this bake-off; Gemma / Qwen3 / Phi / 7B all passed `early_transfer_request`.
6. **Policy changes applied** — dual DNC+abuse OK; ask-again on no_parts/no_time OK; early transfer still hard-fail.
