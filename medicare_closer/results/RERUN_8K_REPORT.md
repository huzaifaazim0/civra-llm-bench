# Rerun Results — 8k context + prompt/SOA fixes

**When:** 2026-07-21 ~15:16–15:35 UTC  
**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Context:** `MAX_MODEL_LEN=8192`, `CONTEXT_TURNS=8`, `MAX_TOKENS=512`  
**Changes vs prior run:** longer context, anti-loop / SOA-before-plan prompts, flag normalize, SOA state-machine gate

## Headline

| Mode | Before (4k) | After (8k + fixes) | Delta |
|------|-------------|--------------------|-------|
| Structured scenario pass | **5/15** | **5/15** | flat |
| Structured turn OK | 68.8% | **62.3%** | worse |
| Freeform gen (all scenarios) | 15/15 | 15/15 | flat |
| Freeform judge (same 9) | **2/9** pass | **3/9** pass | +1 (`abuse_hostile`) |
| Avg hard_safety (9) | ~3.2 | **3.11** | flat/slightly down |

**Bottom line:** Raising context to 8k and tightening prompts did **not** fix the core product bugs (SOA-before-pitch, re-ask loops, firm employer close). One real win: **abuse/hostile now terminates correctly**. Structured got stricter/noisier, not better.

## Structured matrix (after)

PASS: `dnc_immediate`, `rural_network_concern`, `giveback_vs_medicaid`, `va_tricare_ok`, `abuse_hostile`  
FAIL: happy enroll, employer, callback, side topic, dual, angry, etc.

Notable regressions vs 4k structured: lost `employer_conflict`, `callback_busy`, `side_topic_tangent` (SOA gate + wrong actions like callback→`dnc`).

## Freeform judge (same 9 you scored)

| Scenario | Before | After | Notes |
|----------|:------:|:-----:|-------|
| dnc_immediate | PASS | PASS | Still OK |
| callback_busy | PASS | PASS | Still clean |
| abuse_hostile | FAIL | **PASS** | Now ends contact + DNC registry |
| happy_enroll_otc | FAIL | FAIL | Still loops zip/DOB; pitches before clear SOA |
| employer_conflict | FAIL | FAIL | Still pitches GiveBack before employer disclosure |
| giveback_vs_medicaid | FAIL | FAIL | Wrong GiveBack pitch to dual, then food card |
| dual_snp_attestation | FAIL | FAIL | Right plan, early pitch |
| angry_deescalate | FAIL | FAIL | SSN / recording loops |
| side_topic_tangent | FAIL | FAIL | Good ack, then re-asks recording/DM |

Scores written under:  
`results/freeform_20260721T152937Z/judge_packets/scores_rerun/`

## What this means for next fixes

**Not fixed by 8k alone.** The agent still does not *use* prior answers in freeform (re-asks every turn). Next levers (in order):

1. **Deterministic dialog controller** (code owns step; LLM only fills `message`) — biggest ROI for closer
2. Or **structured-only interactive** with prior-state injection that freeform currently lacks
3. Then bake-off **Gemma-4-E4B** at 8k
4. Larger params only after (1)

Artifacts:
- Structured: `results/closer_correctness_qwen-qwen2-5-7b-instruct.md`
- Freeform: `results/freeform_20260721T152937Z/`
