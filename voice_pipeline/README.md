# Voice pipeline concurrency stress

Measures **end-to-end TTFA** (call start → first playable TTS audio) across **18 STT×LLM×TTS** combos on one 20GB Ada GPU.

## Combos

| Stage | Options |
|-------|---------|
| STT | `parakeet` (WS `:37283`), `ifw` (insanely-fast-whisper in-process) |
| LLM | `moe` (`QuixiAI/Qwen3-30B-A3B-AWQ`), `3b`, `7b` via vLLM `:8000` |
| TTS | `kokoro` (WS `:32432`), `melo`, `neutts` (Air Q4 `infer_stream`) |

## Quick start

```bash
./commands.sh setup
./commands.sh run --stt parakeet --llm 3b --tts kokoro --smoke
./commands.sh run --stt parakeet --llm 3b --tts kokoro --find-limit
./commands.sh run_matrix --find-limit   # all 18 → results/*.json + RESULTS.md
```

## VRAM policy

- **MoE** ≈16GB → LLM exclusive on GPU (`gpu_memory_utilization=0.95`). Parakeet starts as `v2-fp16-cpu`, Kokoro as `DEVICE=cpu`; IFW/Melo/NeuTTS on CPU (`CUDA_VISIBLE_DEVICES=` for NeuTTS so llama-cpp does not touch the full GPU).
- **3B/7B** leave headroom so Parakeet + Kokoro can stay on GPU when free VRAM allows.

## Metrics

Per request: `stt_ms`, `llm_ttft_ms`, `tts_ttfa_ms`, **`e2e_ttfa_ms`**, `e2e_total_ms`.  
Find-limit stops when `e2e_ttfa_p95 > STOP_TTFA_MS` (default **4000**) or error rate > 5%.

## Layout

```
adapters/          thin clients over sibling engines
fixtures/          caller WAVs
pipeline_stress.py orchestrator + concurrency ramp
results/           combo JSON + RESULTS.md
commands.sh        setup / servers / run / matrix
```

See [results/RESULTS.md](results/RESULTS.md) for the latest 18-combo table.
