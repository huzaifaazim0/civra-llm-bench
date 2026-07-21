# Medicare Fronter Stress Sessions Report

**Model:** `microsoft/Phi-4-mini-instruct`  
**Generated:** 2026-07-21T03:16:24.189998+00:00  
**Concurrency:** 10  
**Mode:** `stress_sessions`  

## Definitions

- **TTFT** — time to first streamed token (ms).
- **Full generation** — wall time for complete JSON response (ms).
- **TPS** — completion tokens / decode time after first token.
- **Error rate** — fraction of turns failing schema or flow checks.

## Results

- Turns: 38
- OK rate: 0.8947
- Error rate: 0.1053
- Schema OK rate: 1.0
- TTFT p50 / p95 / max (ms): 121.6 / 234.36 / 259.33
- Full gen p50 / p95 / max (ms): 3299.84 / 3729.38 / 4034.58
- TPS avg / min: 28.039 / 26.037
