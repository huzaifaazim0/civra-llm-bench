# Medicare Fronter Stress Sessions Report

**Model:** `Qwen/Qwen2.5-7B-Instruct`  
**Generated:** 2026-07-21T03:30:24.658248+00:00  
**Concurrency:** 10  
**Mode:** `stress_sessions`  

## Definitions

- **TTFT** — time to first streamed token (ms).
- **Full generation** — wall time for complete JSON response (ms).
- **TPS** — completion tokens / decode time after first token.
- **Error rate** — fraction of turns failing schema or flow checks.

## Results

- Turns: 38
- OK rate: 0.9474
- Error rate: 0.0526
- Schema OK rate: 1.0
- TTFT p50 / p95 / max (ms): 179.37 / 189.55 / 190.2
- Full gen p50 / p95 / max (ms): 7084.57 / 7400.28 / 7650.99
- TPS avg / min: 17.73 / 17.479
