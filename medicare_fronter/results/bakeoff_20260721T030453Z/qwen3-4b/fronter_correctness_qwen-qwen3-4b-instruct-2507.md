# Medicare Fronter Correctness Report

**Model:** `Qwen/Qwen3-4B-Instruct-2507`  
**Generated:** 2026-07-21T03:11:33.062962+00:00  
**Scenarios:** 12  
**Turns:** 44  
**Pass rate (hard checks):** 0.9318  
**Schema OK rate:** 1.0  
**Error rate:** 0.0682  

## Latency

- TTFT avg / p50 / p95 / max (ms): 105.6 / 70.76 / 154.8 / 850.16
- Full generation avg / p50 / p95 / max (ms): 2849.89 / 2781.8 / 3367.47 / 3711.32
- TPS avg / p50 / min: 31.288 / 31.32 / 31.117

## Per scenario

| Scenario | Turns | Pass | Fail | Error rate |
|----------|------:|-----:|-----:|-----------:|
| `happy_65_plus` | 4 | 4 | 0 | 0.0 |
| `happy_under65_disability` | 5 | 4 | 1 | 0.2 |
| `under65_no_disability` | 5 | 4 | 1 | 0.2 |
| `no_time` | 2 | 2 | 0 | 0.0 |
| `no_parts` | 3 | 2 | 1 | 0.3333 |
| `side_topic_then_continue` | 5 | 5 | 0 | 0.0 |
| `vague_then_clarify` | 5 | 5 | 0 | 0.0 |
| `dnc_mid_flow` | 3 | 3 | 0 | 0.0 |
| `abuse_end` | 2 | 2 | 0 | 0.0 |
| `partial_parts_clarify` | 3 | 3 | 0 | 0.0 |
| `early_transfer_request` | 5 | 5 | 0 | 0.0 |
| `not_interested_as_no_time` | 2 | 2 | 0 | 0.0 |

## Error taxonomy

- **state_machine:** 2
- **next:** 2
- **message_soft:** 1
- **action:** 1
