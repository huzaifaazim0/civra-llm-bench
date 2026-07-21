# Medicare Fronter Correctness Report

**Model:** `Qwen/Qwen2.5-3B-Instruct`  
**Generated:** 2026-07-21T03:07:07.931260+00:00  
**Scenarios:** 12  
**Turns:** 44  
**Pass rate (hard checks):** 0.7727  
**Schema OK rate:** 1.0  
**Error rate:** 0.2273  

## Latency

- TTFT avg / p50 / p95 / max (ms): 74.87 / 56.34 / 111.99 / 435.55
- Full generation avg / p50 / p95 / max (ms): 2238.35 / 2212.67 / 2684.55 / 2868.42
- TPS avg / p50 / min: 40.518 / 40.51 / 40.313

## Per scenario

| Scenario | Turns | Pass | Fail | Error rate |
|----------|------:|-----:|-----:|-----------:|
| `happy_65_plus` | 4 | 3 | 1 | 0.25 |
| `happy_under65_disability` | 5 | 4 | 1 | 0.2 |
| `under65_no_disability` | 5 | 2 | 3 | 0.6 |
| `no_time` | 2 | 2 | 0 | 0.0 |
| `no_parts` | 3 | 2 | 1 | 0.3333 |
| `side_topic_then_continue` | 5 | 5 | 0 | 0.0 |
| `vague_then_clarify` | 5 | 5 | 0 | 0.0 |
| `dnc_mid_flow` | 3 | 2 | 1 | 0.3333 |
| `abuse_end` | 2 | 2 | 0 | 0.0 |
| `partial_parts_clarify` | 3 | 2 | 1 | 0.3333 |
| `early_transfer_request` | 5 | 4 | 1 | 0.2 |
| `not_interested_as_no_time` | 2 | 1 | 1 | 0.5 |

## Error taxonomy

- **next:** 6
- **state_fields:** 4
- **action:** 4
- **message_soft:** 1
- **state_machine:** 1
