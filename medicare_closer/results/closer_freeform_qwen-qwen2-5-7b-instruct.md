# Medicare Closer Correctness Report

**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T18:08:16.790654+00:00  
**Mode:** `correctness_freeform`  
**Scenarios:** 15  
**Turns:** 77  
**Pass rate (hard checks):** 1.0  
**Schema OK rate:** 1.0  
**Error rate:** 0.0  

## Latency

- TTFT avg / p50 / p95 / max (ms): 151.03 / 117.96 / 383.08 / 461.56
- Full generation avg / p50 / p95 / max (ms): 2326.21 / 2510.23 / 3468.3 / 4108.7
- TPS avg / p50 / min: 18.826 / 18.74 / 18.224

## Per scenario

| Scenario | Turns | Pass | Fail | Error rate |
|----------|------:|-----:|-----:|-----------:|
| `happy_enroll_otc` | 15 | 15 | 0 | 0.0 |
| `ssn_medicaid_fallback` | 10 | 10 | 0 | 0.0 |
| `angry_deescalate_continue` | 4 | 4 | 0 | 0.0 |
| `employer_conflict` | 6 | 6 | 0 | 0.0 |
| `dnc_immediate` | 2 | 2 | 0 | 0.0 |
| `no_better_plan` | 5 | 5 | 0 | 0.0 |
| `not_decision_maker` | 4 | 4 | 0 | 0.0 |
| `callback_busy` | 3 | 3 | 0 | 0.0 |
| `side_topic_tangent` | 5 | 5 | 0 | 0.0 |
| `rural_network_concern` | 4 | 4 | 0 | 0.0 |
| `giveback_vs_medicaid` | 4 | 4 | 0 | 0.0 |
| `dual_snp_attestation` | 4 | 4 | 0 | 0.0 |
| `va_tricare_ok` | 4 | 4 | 0 | 0.0 |
| `abuse_hostile` | 3 | 3 | 0 | 0.0 |
| `skip_optional_verify` | 4 | 4 | 0 | 0.0 |
