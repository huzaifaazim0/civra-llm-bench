# Voice pipeline stress results

Generated from `/root/.cvr/llm_stress_test/voice_pipeline/results`.

**Hardware:** 1× NVIDIA RTX 4000 SFF Ada 20GB.  
**Stop criteria:** e2e TTFA p95 > 4000 ms or error rate > 5%.  
**MoE note:** LLM exclusive on GPU; Parakeet/Kokoro run as CPU servers; IFW/Melo/NeuTTS on CPU (`CUDA_VISIBLE_DEVICES=` for NeuTTS).

## By max stable concurrency

| STT | LLM | TTS | max_stable | e2e_ttfa_p50@1 (ms) | e2e_ttfa_p95@1 (ms) | stop | ok |
|-----|-----|-----|------------|--------------------:|--------------------:|------|----|
| parakeet | 3b | kokoro | 16 | 215 | 215 | — | True |
| parakeet | 3b | melo | 16 | 299 | 299 | — | True |
| parakeet | 7b | kokoro | 16 | 258 | 258 | — | True |
| parakeet | 7b | melo | 16 | 316 | 316 | — | True |
| ifw | 3b | kokoro | 4 | 815 | 815 | e2e_ttfa_p95>4000.0 | True |
| ifw | 3b | melo | 4 | 619 | 619 | e2e_ttfa_p95>4000.0 | True |
| ifw | 7b | melo | 4 | 614 | 614 | e2e_ttfa_p95>4000.0 | True |
| parakeet | 3b | neutts | 4 | 1218 | 1218 | — | True |
| ifw | 3b | neutts | 2 | 2030 | 2030 | e2e_ttfa_p95>4000.0 | True |
| ifw | 7b | kokoro | 2 | 844 | 844 | e2e_ttfa_p95>4000.0 | True |
| parakeet | moe | kokoro | 2 | 1350 | 1350 | e2e_ttfa_p95>4000.0 | True |
| parakeet | moe | melo | 2 | 995 | 995 | e2e_ttfa_p95>4000.0 | True |
| ifw | 7b | neutts | 1 | 3197 | 3197 | e2e_ttfa_p95>4000.0 | True |
| parakeet | 7b | neutts | 1 | 2446 | 2446 | e2e_ttfa_p95>4000.0 | True |
| ifw | moe | kokoro | 0 | 25202 | 25202 | e2e_ttfa_p95>4000.0 | True |
| ifw | moe | melo | 0 | 16353 | 16353 | e2e_ttfa_p95>4000.0 | True |
| ifw | moe | neutts | 0 | 373538 | 373538 | e2e_ttfa_p95>4000.0 | True |
| parakeet | moe | neutts | 0 | 270385 | 270385 | e2e_ttfa_p95>4000.0 | True |

## By e2e TTFA p50 at concurrency=1

| STT | LLM | TTS | max_stable | e2e_ttfa_p50@1 (ms) | e2e_ttfa_p95@1 (ms) | stop | ok |
|-----|-----|-----|------------|--------------------:|--------------------:|------|----|
| parakeet | 3b | kokoro | 16 | 215 | 215 | — | True |
| parakeet | 7b | kokoro | 16 | 258 | 258 | — | True |
| parakeet | 3b | melo | 16 | 299 | 299 | — | True |
| parakeet | 7b | melo | 16 | 316 | 316 | — | True |
| ifw | 7b | melo | 4 | 614 | 614 | e2e_ttfa_p95>4000.0 | True |
| ifw | 3b | melo | 4 | 619 | 619 | e2e_ttfa_p95>4000.0 | True |
| ifw | 3b | kokoro | 4 | 815 | 815 | e2e_ttfa_p95>4000.0 | True |
| ifw | 7b | kokoro | 2 | 844 | 844 | e2e_ttfa_p95>4000.0 | True |
| parakeet | moe | melo | 2 | 995 | 995 | e2e_ttfa_p95>4000.0 | True |
| parakeet | 3b | neutts | 4 | 1218 | 1218 | — | True |
| parakeet | moe | kokoro | 2 | 1350 | 1350 | e2e_ttfa_p95>4000.0 | True |
| ifw | 3b | neutts | 2 | 2030 | 2030 | e2e_ttfa_p95>4000.0 | True |
| parakeet | 7b | neutts | 1 | 2446 | 2446 | e2e_ttfa_p95>4000.0 | True |
| ifw | 7b | neutts | 1 | 3197 | 3197 | e2e_ttfa_p95>4000.0 | True |
| ifw | moe | melo | 0 | 16353 | 16353 | e2e_ttfa_p95>4000.0 | True |
| ifw | moe | kokoro | 0 | 25202 | 25202 | e2e_ttfa_p95>4000.0 | True |
| parakeet | moe | neutts | 0 | 270385 | 270385 | e2e_ttfa_p95>4000.0 | True |
| ifw | moe | neutts | 0 | 373538 | 373538 | e2e_ttfa_p95>4000.0 | True |

## Takeaways

- Best concurrency on this card: **Parakeet → 3B/7B → Kokoro/Melo** held **16** concurrent users under the TTFA budget (sweep max 16).
- IFW (batch Whisper) is slower to first audio; stable concurrency typically **2–4**.
- NeuTTS Air Q4 streams well on GPU but collapses under MoE (forced CPU) — TTFA often tens of seconds; max_stable **0–4**.
- MoE pipelines work with CPU STT/TTS but are latency-bound, not concurrency-bound like the 3B/7B + GPU audio stack.
