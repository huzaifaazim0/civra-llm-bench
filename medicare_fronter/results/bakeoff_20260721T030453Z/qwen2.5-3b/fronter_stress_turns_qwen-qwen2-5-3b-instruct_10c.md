# Medicare Fronter Stress Turns Report

**Model:** `Qwen/Qwen2.5-3B-Instruct`  
**Generated:** 2026-07-21T03:07:13.301403+00:00  
**Concurrency:** 10  
**Mode:** `stress_turns`  

## Definitions

- **TTFT** — time to first streamed token (ms).
- **Full generation** — wall time for complete JSON response (ms).
- **TPS** — completion tokens / decode time after first token.
- **Error rate** — fraction of turns failing schema or flow checks.

## Results

- Turns: 20
- OK rate: 1.0
- Error rate: 0.0
- Schema OK rate: 1.0
- TTFT p50 / p95 / max (ms): 143.45 / 145.18 / 145.4
- Full gen p50 / p95 / max (ms): 2389.13 / 2607.31 / 2659.36
- TPS avg / min: 38.506 / 37.936
