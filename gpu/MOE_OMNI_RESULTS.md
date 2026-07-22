# Stress results — MoE + Omni (independent campaigns)

**Host:** 1× NVIDIA RTX 4000 SFF Ada **20GB**  
**Date:** 2026-07-22

---

## 1) MoE text — `QuixiAI/Qwen3-30B-A3B-AWQ`

~30B total / ~3B active, AWQ marlin via vLLM 0.21. Thinking disabled (`chat_template_kwargs.enable_thinking=false`).  
KV headroom ~1.6GB / 17k tokens @ 4k ctx.

| Metric | Value |
|--------|------:|
| Max stable concurrency (TTFT p95 ≤ 1500ms, min TPS ≥ 4) | **211** |
| Limit hit | 221 (TTFT p95 1537ms) |

| Concurrent | TTFT p95 | TPS min | Aggregate tok/s | Errors |
|----------:|---------:|--------:|----------------:|-------:|
| 20 | **109ms** | 24.2 | 376 | 0 |
| 40 | **154ms** | 25.6 | 734 | 0 |
| 60 | **205ms** | 20.7 | 862 | 0 |

Artifacts: `stress_results_find_limit-qwen3-30b-a3b-awq.json`, `stress_results_{20,40,60}c_qwen3-30b-a3b-awq.json`

---

## 2) Audio → text — `Qwen/Qwen2.5-Omni-3B`

**Engine:** transformers (vLLM-Omni default stage deploy expects **2 GPUs**; failed on this single card).  
Metrics = sequential single-copy latency (not true parallel concurrency).

| Batch size (sequential) | wall p50 | wall p95 | effective QPS | Errors |
|------------------------:|---------:|---------:|--------------:|-------:|
| 1 | 584ms | 584ms | 1.30 | 0 |
| 2 | 1.86s | 3.00s | 0.49 | 0 |
| 4 | 1.85s | 3.02s | 0.51 | 0 |

Artifact: `omni_transformers_results.json`

---

## 3) Audio → audio — listen gallery

Same Omni-3B via transformers, `return_audio=True`.  
**Play files in** [`omni_listen_gallery/`](omni_listen_gallery/) — see [`LISTEN_ME.md`](omni_listen_gallery/LISTEN_ME.md).

| Clip | Duration | Wall | RTF |
|------|----------:|-----:|----:|
| greeting | 5.9s | 7.9s | 0.74 |
| medicare_explain | 33.2s | 85.4s | 0.39 |
| clarify_zip | 25.6s | 56.3s | 0.45 |
| empathy | 11.7s | 17.4s | 0.68 |
| repeat_back | 13.4s | 19.7s | 0.68 |
| longform | 33.5s | 86.9s | 0.39 |
| rephrase_short | 7.8s | 10.6s | 0.73 |
| status_update | 5.9s | 7.7s | 0.77 |

RTF &lt; 1 means generation slower than real-time on this GPU (expected for full thinker+talker+code2wav).

Quality notes while listening: TTS input fixtures are robotic; Omni sometimes mis-hears (e.g. “ZIP” → “IP” on `clarify_zip`). Speech output itself is intelligible.

Artifacts: `omni_audio_to_audio_gallery.json`, `omni_listen_gallery/aa_*.wav`

---

## Comparison snapshot

| Campaign | Concurrent users (SLO) | Notes |
|----------|------------------------:|-------|
| Dense 14B AWQ (prior) | ~261 max / ~81 @ TTFT&lt;500ms | text rephrase |
| MoE 30B-A3B AWQ | **211** max / **60+** easy @ TTFT&lt;500ms | text; higher tok/s than 14B at mid load |
| Omni-3B A→T | ~0.5 QPS sequential | not multi-user concurrent on 1×20GB |
| Omni-3B A→A | 1 stream | listen gallery only |
