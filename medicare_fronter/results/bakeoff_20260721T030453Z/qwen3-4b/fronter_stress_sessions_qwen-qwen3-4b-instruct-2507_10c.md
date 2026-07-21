# Medicare Fronter Stress Sessions Report

**Model:** `Qwen/Qwen3-4B-Instruct-2507`  
**Generated:** 2026-07-21T03:11:55.857702+00:00  
**Concurrency:** 10  
**Mode:** `stress_sessions`  

## Definitions

- **TTFT** — time to first streamed token (ms).
- **Full generation** — wall time for complete JSON response (ms).
- **TPS** — completion tokens / decode time after first token.
- **Error rate** — fraction of turns failing schema or flow checks.

## Results

- Turns: 38
- OK rate: 0.8684
- Error rate: 0.1316
- Schema OK rate: 1.0
- TTFT p50 / p95 / max (ms): 107.29 / 145.54 / 145.91
- Full gen p50 / p95 / max (ms): 2999.13 / 3419.3 / 3420.81
- TPS avg / min: 29.188 / 28.74
