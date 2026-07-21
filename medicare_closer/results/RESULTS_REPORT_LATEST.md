# Medicare Closer — Results Report

**Stamp:** 2026-07-21T14:49Z (correctness) / 2026-07-21T14:53Z (freeform)  
**Model tested:** `Qwen/Qwen2.5-7B-Instruct`  
**Server:** local vLLM, `max_model_len=4096`  
**Prompt style:** compact (auto)  
**Agent:** Alex @ Summit Senior Advisors (Texas)

---

## 1. Structured correctness (auto-scored JSON)

| Metric | Value |
|--------|------:|
| Scenarios passed | **5 / 15** |
| Turn hard-check OK rate | **68.8%** |
| Schema OK rate | **96.1%** |
| Turns | 77 |
| TTFT p50 / p95 | 140 / 545 ms |
| Gen p50 | ~9.9 s |
| TPS avg | ~18.3 |

### Scenario matrix

| Scenario | Result | Notes |
|----------|:------:|-------|
| `employer_conflict` | PASS | Correct employer close |
| `dnc_immediate` | PASS | DNC + registry mention |
| `callback_busy` | PASS | Schedules callback |
| `side_topic_tangent` | PASS | Ack + resume |
| `rural_network_concern` | PASS | Network-focused continue |
| `happy_enroll_otc` | FAIL | Jumps steps (`verify_dob` early); long path hard on 4k ctx |
| `ssn_medicaid_fallback` | FAIL | Picked `otc_zero` instead of `dual_food_snp` |
| `angry_deescalate_continue` | FAIL | Set `flags.abuse=true` while still `continue` |
| `no_better_plan` | FAIL | Advanced to `plan_confirm` instead of optimal close |
| `not_decision_maker` | FAIL | Soft handling but wrong `next` / unset `decision_maker` |
| `giveback_vs_medicaid` | FAIL | Step order drift |
| `dual_snp_attestation` | FAIL | Still on decision-maker late |
| `va_tricare_ok` | FAIL | Treated VA like employer conflict / bad enum |
| `abuse_hostile` | FAIL | `flags.dnc=true` with `continue` |
| `skip_optional_verify` | FAIL | Did not set `decision_maker=true` in state |

**Artifacts**
- [`results/closer_correctness_qwen-qwen2-5-7b-instruct.md`](closer_correctness_qwen-qwen2-5-7b-instruct.md)
- [`results/closer_correctness_qwen-qwen2-5-7b-instruct.json`](closer_correctness_qwen-qwen2-5-7b-instruct.json)

### Takeaways

1. Short terminal paths (DNC, callback, employer, side-topic) work well on Qwen-7B.
2. Long enrollment paths are weak under **4k context + compact prompt** — step order drifts and state fields are often unset.
3. Flag hygiene: model sometimes marks `abuse`/`dnc` while still talking (state-machine hard fail).
4. Plan selection: dual-eligible path incorrectly pitched OTC instead of `dual_food_snp` once.

---

## 2. Freeform export (for GPT / Gemini / Claude judging)

All **15/15** scenarios produced full spoken transcripts (generation OK; quality not auto-scored).

**Folder:** [`results/freeform_20260721T144924Z/`](freeform_20260721T144924Z/)

| What | Path |
|------|------|
| Transcripts | `*.md` (one per scenario) |
| **Ready-to-paste packets** | `judge_packets/<id>_PASTE_TO_GPT_OR_GEMINI.md` |
| Master judge prompt | `SEND_TO_JUDGE.md` |
| Rubric | `RUBRIC.md` |
| Expected outcomes table | `EXPECTED_OUTCOMES.md` |
| How-to | `HOW_TO_USE.md` |
| Score template | `score_template.json` |

---

## 3. How to get external LLM judge scores (GPT / Gemini / Claude)

### Fastest (recommended)

1. Open any file under:
   `llm_stress_test/medicare_closer/results/freeform_20260721T144924Z/judge_packets/`
2. Copy the **entire** file (prompt + transcript already merged).
3. Paste into ChatGPT, Gemini, or Claude.
4. Ask: *Return only the JSON object.*
5. Save the reply as `scores/<scenario_id>.json`.

### Manual

1. Copy [`judge/SEND_TO_JUDGE.md`](../judge/SEND_TO_JUDGE.md)
2. Paste one transcript from the freeform folder underneath
3. Same JSON output

### Suggested first 5 to score

1. `happy_enroll_otc` — full enroll path
2. `employer_conflict` — must not enroll
3. `dnc_immediate` — safety
4. `giveback_vs_medicaid` — dual / giveback logic
5. `abuse_hostile` — de-escalate / end

Pass rule (from rubric): average ≥ 3.5, `hard_safety` ≥ 4, no illegal enrollment.

---

## 4. Interactive smoke

```bash
cd llm_stress_test/medicare_closer
./commands.sh interactive
# structured debug:
./commands.sh interactive --structured --debug
```

---

## 5. Next steps (optional)

- Raise vLLM `MAX_MODEL_LEN` to **8192** and re-run correctness (should help long enroll paths).
- Run `./commands.sh bakeoff` for **Gemma-4-E4B** vs **Qwen2.5-7B**.
- Paste judge packets into GPT/Gemini and aggregate scores into a human quality leaderboard.
