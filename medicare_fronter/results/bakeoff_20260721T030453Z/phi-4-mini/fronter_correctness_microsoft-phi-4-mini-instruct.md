# Medicare Fronter Correctness Report

**Model:** `microsoft/Phi-4-mini-instruct`  
**Generated:** 2026-07-21T03:15:58.566802+00:00  
**Scenarios:** 12  
**Turns:** 44  
**Pass rate (hard checks):** 0.9091  
**Schema OK rate:** 1.0  
**Error rate:** 0.0909  

## Latency

- TTFT avg / p50 / p95 / max (ms): 101.47 / 66.83 / 140.74 / 975.76
- Full generation avg / p50 / p95 / max (ms): 2889.99 / 2853.97 / 3309.09 / 4070.93
- TPS avg / p50 / min: 32.619 / 32.65 / 32.283

## Per scenario

| Scenario | Turns | Pass | Fail | Error rate |
|----------|------:|-----:|-----:|-----------:|
| `happy_65_plus` | 4 | 4 | 0 | 0.0 |
| `happy_under65_disability` | 5 | 5 | 0 | 0.0 |
| `under65_no_disability` | 5 | 5 | 0 | 0.0 |
| `no_time` | 2 | 1 | 1 | 0.5 |
| `no_parts` | 3 | 2 | 1 | 0.3333 |
| `side_topic_then_continue` | 5 | 5 | 0 | 0.0 |
| `vague_then_clarify` | 5 | 5 | 0 | 0.0 |
| `dnc_mid_flow` | 3 | 3 | 0 | 0.0 |
| `abuse_end` | 2 | 2 | 0 | 0.0 |
| `partial_parts_clarify` | 3 | 2 | 1 | 0.3333 |
| `early_transfer_request` | 5 | 5 | 0 | 0.0 |
| `not_interested_as_no_time` | 2 | 1 | 1 | 0.5 |

## Error taxonomy

- **action:** 2
- **state_machine:** 1
- **next:** 1
