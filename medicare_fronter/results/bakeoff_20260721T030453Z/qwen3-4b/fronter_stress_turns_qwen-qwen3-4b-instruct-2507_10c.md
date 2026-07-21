# Medicare Fronter Stress Turns Report

**Model:** `Qwen/Qwen3-4B-Instruct-2507`  
**Generated:** 2026-07-21T03:11:39.861172+00:00  
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
- TTFT p50 / p95 / max (ms): 224.49 / 230.71 / 268.85
- Full gen p50 / p95 / max (ms): 3097.26 / 3473.4 / 3511.87
- TPS avg / min: 28.233 / 27.506
