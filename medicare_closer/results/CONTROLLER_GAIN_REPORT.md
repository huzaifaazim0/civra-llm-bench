# Controller architecture — gain report

**Date:** 2026-07-21  
**Model:** `Qwen/Qwen2.5-7B-Instruct` @ 8k  
**Change:** Code-owned step controller + voice-only LLM (warm / emotional wording)

## Theory

Small open models fail when they must **own the whole closer** (SOA gates, plan choice, terminals, no re-ask loops) *and* sound human. Split the job:

| Layer | Owner | Job |
|-------|--------|-----|
| Flow / compliance | `controller.py` | Step order, state, plan pick, DNC/employer/DM/abuse terminals |
| Speech | LLM via `voice.py` | Warm, emotionally intelligent spoken lines only |

`USE_CONTROLLER=1` (default). Set `USE_CONTROLLER=0` for the old LLM-owns-flow path.

## Structured correctness (hard action/next/state)

| Run | Pass | Turn ok |
|-----|-----:|--------:|
| Baseline (LLM owns flow, 4k) | **5/15** | ~0.78 |
| After 8k + prompt gates | **5/15** | ~0.62 |
| **Controller + voice LLM** | **15/15** | **1.00** |

**Gain: +10 scenarios (+200% vs 5/15). Perfect hard pass rate.**

## Freeform generation + soft judge

| Run | Gen “pass” (spoke every turn) | External soft judge |
|-----|------------------------------:|--------------------:|
| First freeform | mostly generated | **2/9** pass |
| 8k rerun | generated | **3/9** pass |
| **Controller freeform** (`freeform_20260721T180517Z`) | **15/15** | **12/15** pass |

**Soft-judge gain: 2/9 → 3/9 → 12/15** (same pass rule: avg ≥ 3.5, hard_safety ≥ 4, no illegal enrollment).

### Soft-judge dimension averages (controller freeform)

| Dimension | Avg |
|-----------|----:|
| compliance_order | 3.33 |
| redirect_handling | 4.33 |
| naturalness | 3.40 |
| outcome_correctness | 4.53 |
| plan_choice | 4.93 |
| hard_safety | 4.47 |
| Mean scenario avg | 4.17 |

### Soft-judge fails (3)

| Scenario | Why |
|----------|-----|
| `ssn_medicaid_fallback` | Enrolled without recording / plan-availability / clear SOA (hard_safety 2) |
| `rural_network_concern` | Re-ask loop on current-plan; stalled (avg 3.17) |
| `dual_snp_attestation` | Assumed existing dual SNP benefits; enroll framing without SOA (hard_safety 3) |

Full write-up: `results/freeform_20260721T180517Z/JUDGE_REPORT.md`  
Scores: `results/freeform_20260721T180517Z/judge_packets/scores/*.json`

Controller freeform mostly eliminated prior soft-judge killers (`hard_safety`, SOA-before-pitch on clean paths, DNC/employer/callback terminals). Remaining gaps are **skipped early gates on multi-answer dumps**, **stiffness / thin explanations**, and a **few edge-path compliance slips**.

## Sample voice (controller)

Angry caller — empathize then soft ask:

> I hear you feeling frustrated, and I truly apologize… How about we keep this quick, or maybe I can call back another time…

Side topic — ack then resume:

> That sounds like quite an adventure! How has your current plan been working out for you so far?

## How to re-test

```bash
cd llm_stress_test/medicare_closer
USE_CONTROLLER=1 ./commands.sh correctness
USE_CONTROLLER=1 TEMPERATURE=0.65 ./commands.sh correctness_freeform
# Interactive (emotional voice):
USE_CONTROLLER=1 ./commands.sh interactive
```

Judge packets: `results/freeform_<timestamp>/judge_packets/*_PASTE_TO_GPT_OR_GEMINI.md`

## Verdict

The theory holds: **controller for correctness, LLM for emotion**. Structured score went from **5/15 → 15/15**. Soft judge went from **2/9–3/9 → 12/15**. Speech stays mostly natural; flow is no longer at the mercy of a 7B model’s JSON discipline. Next soft gains: force recording/SOA when the caller dumps consent early, kill the rural re-ask, and tighten dual-path enrollment framing.
