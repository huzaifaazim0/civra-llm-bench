# Medicare Fronter Stress Turns Report

**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T03:29:49.052002+00:00  
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
- TTFT p50 / p95 / max (ms): 299.53 / 306.59 / 309.51
- Full gen p50 / p95 / max (ms): 7371.82 / 7518.89 / 7578.75
- TPS avg / min: 17.498 / 17.388
