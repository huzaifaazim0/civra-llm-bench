# Medicare Fronter Correctness Report

**Model:** `google/gemma-4-E4B-it`  
**Generated:** 2026-07-21T03:23:23.263942+00:00  
**Scenarios:** 12  
**Turns:** 44  
**Pass rate (hard checks):** 1.0  
**Schema OK rate:** 1.0  
**Error rate:** 0.0  

## Latency

- TTFT avg / p50 / p95 / max (ms): 153.64 / 84.26 / 187.37 / 2098.94
- Full generation avg / p50 / p95 / max (ms): 3567.48 / 3508.85 / 3843.31 / 5519.12
- TPS avg / p50 / min: 26.757 / 26.75 / 26.652

## Per scenario

| Scenario | Turns | Pass | Fail | Error rate |
|----------|------:|-----:|-----:|-----------:|
| `happy_65_plus` | 4 | 4 | 0 | 0.0 |
| `happy_under65_disability` | 5 | 5 | 0 | 0.0 |
| `under65_no_disability` | 5 | 5 | 0 | 0.0 |
| `no_time` | 2 | 2 | 0 | 0.0 |
| `no_parts` | 3 | 3 | 0 | 0.0 |
| `side_topic_then_continue` | 5 | 5 | 0 | 0.0 |
| `vague_then_clarify` | 5 | 5 | 0 | 0.0 |
| `dnc_mid_flow` | 3 | 3 | 0 | 0.0 |
| `abuse_end` | 2 | 2 | 0 | 0.0 |
| `partial_parts_clarify` | 3 | 3 | 0 | 0.0 |
| `early_transfer_request` | 5 | 5 | 0 | 0.0 |
| `not_interested_as_no_time` | 2 | 2 | 0 | 0.0 |
