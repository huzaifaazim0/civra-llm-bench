# Medicare Fronter Stress Turns Report

**Model:** `google/gemma-4-E4B-it`  
**Generated:** 2026-07-21T03:23:31.654617+00:00  
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
- TTFT p50 / p95 / max (ms): 376.87 / 379.69 / 379.84
- Full gen p50 / p95 / max (ms): 3970.96 / 4226.56 / 4350.39
- TPS avg / min: 24.26 / 23.659
