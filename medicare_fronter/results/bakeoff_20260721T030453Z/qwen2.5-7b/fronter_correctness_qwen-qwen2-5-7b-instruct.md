# Medicare Fronter Correctness Report

**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T03:29:33.854829+00:00  
**Scenarios:** 12  
**Turns:** 44  
**Pass rate (hard checks):** 0.9545  
**Schema OK rate:** 1.0  
**Error rate:** 0.0455  

## Latency

- TTFT avg / p50 / p95 / max (ms): 167.74 / 119.01 / 276.51 / 805.65
- Full generation avg / p50 / p95 / max (ms): 6884.05 / 6967.67 / 7371.14 / 7604.55
- TPS avg / p50 / min: 18.364 / 18.36 / 18.337

## Per scenario

| Scenario | Turns | Pass | Fail | Error rate |
|----------|------:|-----:|-----:|-----------:|
| `happy_65_plus` | 4 | 4 | 0 | 0.0 |
| `happy_under65_disability` | 5 | 4 | 1 | 0.2 |
| `under65_no_disability` | 5 | 5 | 0 | 0.0 |
| `no_time` | 2 | 2 | 0 | 0.0 |
| `no_parts` | 3 | 3 | 0 | 0.0 |
| `side_topic_then_continue` | 5 | 5 | 0 | 0.0 |
| `vague_then_clarify` | 5 | 5 | 0 | 0.0 |
| `dnc_mid_flow` | 3 | 3 | 0 | 0.0 |
| `abuse_end` | 2 | 2 | 0 | 0.0 |
| `partial_parts_clarify` | 3 | 2 | 1 | 0.3333 |
| `early_transfer_request` | 5 | 5 | 0 | 0.0 |
| `not_interested_as_no_time` | 2 | 2 | 0 | 0.0 |

## Error taxonomy

- **next:** 2
- **message_soft:** 2
- **state_machine:** 1
- **action:** 1
