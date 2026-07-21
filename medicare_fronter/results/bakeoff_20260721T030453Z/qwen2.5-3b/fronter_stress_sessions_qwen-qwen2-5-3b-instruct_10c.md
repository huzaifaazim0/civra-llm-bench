# Medicare Fronter Stress Sessions Report

**Model:** `Qwen/Qwen2.5-3B-Instruct`  
**Generated:** 2026-07-21T03:07:26.076619+00:00  
**Concurrency:** 10  
**Mode:** `stress_sessions`  

## Definitions

- **TTFT** — time to first streamed token (ms).
- **Full generation** — wall time for complete JSON response (ms).
- **TPS** — completion tokens / decode time after first token.
- **Error rate** — fraction of turns failing schema or flow checks.

## Results

- Turns: 38
- OK rate: 0.6842
- Error rate: 0.3158
- Schema OK rate: 1.0
- TTFT p50 / p95 / max (ms): 88.8 / 182.41 / 189.51
- Full gen p50 / p95 / max (ms): 2346.03 / 2718.11 / 3040.42
- TPS avg / min: 38.069 / 35.601
