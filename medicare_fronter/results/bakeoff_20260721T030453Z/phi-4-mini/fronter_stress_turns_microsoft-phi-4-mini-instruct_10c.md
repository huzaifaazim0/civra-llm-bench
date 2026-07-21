# Medicare Fronter Stress Turns Report

**Model:** `microsoft/Phi-4-mini-instruct`  
**Generated:** 2026-07-21T03:16:06.937825+00:00  
**Concurrency:** 10  
**Mode:** `stress_turns`  

## Definitions

- **TTFT** — time to first streamed token (ms).
- **Full generation** — wall time for complete JSON response (ms).
- **TPS** — completion tokens / decode time after first token.
- **Error rate** — fraction of turns failing schema or flow checks.

## Results

- Turns: 20
- OK rate: 0.95
- Error rate: 0.05
- Schema OK rate: 1.0
- TTFT p50 / p95 / max (ms): 224.35 / 226.03 / 226.56
- Full gen p50 / p95 / max (ms): 3335.72 / 4072.96 / 4497.68
- TPS avg / min: 27.919 / 26.905
