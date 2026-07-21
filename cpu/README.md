# LLM Stress Test — CPU (llama.cpp)

Measure concurrent rephrase performance against **llama-server** on CPU (GGUF models: Gemma, Qwen, Phi, …).

vLLM is not used here — it is GPU-oriented. This path mirrors the same stress scenarios as [`../gpu/`](../gpu/).

**Default targets (single / soak / structured):** TTFT p95 `< 2000ms`, per-user TPS `≥ 1`  
**Find-limit stop criteria:** TTFT p95 `> 8000ms` **or** per-user min TPS `< 1`

All settings live in [`.env`](.env).

---

## Quick start

```bash
cd /root/.cvr/llm_stress_test/cpu

./commands.sh setup
./commands.sh download_model
./commands.sh show_env          # threads, parallel, cores, RAM
./commands.sh start_llama_bg
./commands.sh wait_llama

./commands.sh health
./commands.sh smoke_plain
./commands.sh stress
```

---

## Performance: threads & cores

By default the server uses **all logical CPU cores**:

| Flag | Source | Purpose |
|------|--------|---------|
| `--threads` | `LLAMA_THREADS` or `nproc` | Decode threads |
| `--threads-batch` | `LLAMA_THREADS_BATCH` or same as threads | Prefill / batch threads |
| `--parallel` | `LLAMA_PARALLEL` (default 8) | Concurrent request slots |
| `--ctx-size` | `LLAMA_CTX_SIZE × LLAMA_PARALLEL` | Total KV; each slot gets `LLAMA_CTX_SIZE` |
| `--n-gpu-layers 0` | `LLAMA_N_GPU_LAYERS` | Force CPU-only |

`./commands.sh show_env` prints:

- `host_logical_cores` / `host_physical_cores`
- `ram_total_gb` / `ram_available_gb`
- `LLAMA_THREADS`, `LLAMA_THREADS_BATCH`, `LLAMA_PARALLEL`

Every stress JSON also embeds `server_config` + `host` (cores / RAM) and samples CPU%/RAM during the run.

**Tuning tip:** raising `LLAMA_PARALLEL` allows more concurrent users but multiplies KV-cache RAM (`parallel × ctx_size`). Lower it if you OOM; raise `SWEEP_MAX` carefully.

On multi-socket NUMA hosts, pin with `numactl` if needed (not automated here).

---

## `.env` knobs

| Variable | Purpose |
|----------|---------|
| `MODEL_FILE` | GGUF filename under `models/` |
| `HF_GGUF_REPO` / `HF_GGUF_FILE` | Source for `download_model` |
| `SERVED_MODEL_NAME` | Alias exposed to clients |
| `LLAMA_PORT` / `BASE_URL` | Default **8010** (avoids GPU vLLM on 8000/8001) |
| `LLAMA_THREADS` | Empty = all cores |
| `LLAMA_PARALLEL` | Concurrent slots |
| `LLAMA_CTX_SIZE` | Context **per parallel slot** (total KV = ctx × parallel) |
| `CONCURRENCY` / budgets | CPU SLOs (looser than GPU) |
| `STRUCTURED_MODE` | `openai` (JSON schema) or `prompt` |
| `HF_TOKEN` | Gated GGUFs (e.g. Gemma) |

---

## Models

Default: **Qwen2.5-1.5B Instruct Q4_K_M** (open).

For Gemma (commented in `.env`), set HF token, accept the license, uncomment the Gemma block, then:

```bash
./commands.sh download_model
./commands.sh stop_llama
./commands.sh start_llama_bg && ./commands.sh wait_llama
```

---

## All commands

### Lifecycle

| Command | What it does |
|---------|----------------|
| `./commands.sh setup` | Client venv + download/locate `llama-server` into `bin/` |
| `./commands.sh download_model` | Fetch GGUF into `models/` |
| `./commands.sh show_env` | Threads, parallel, cores, RAM, model |
| `./commands.sh start_llama` | Foreground server |
| `./commands.sh start_llama_bg` | Background (`llama.log`, `llama.pid`) |
| `./commands.sh wait_llama [secs]` | Wait for `/v1/models` |
| `./commands.sh stop_llama` | Stop background server |
| `./commands.sh health` / `smoke_*` | Smoke checks |
| `./commands.sh run_all` | setup → download → start → stress |

### Stress tests (parity with GPU)

| Command | Output |
|---------|--------|
| `stress` | `stress_results_<N>c.json` |
| `stress_soak` | `…_soak.json` |
| `stress_structured` | `…_structured.json` |
| `stress_find_limit` | `stress_results_find_limit.json` |
| `stress_sustained` | `stress_results_sustained_<N>c.json` |

---

## Installing llama-server manually

`setup` tries a prebuilt GitHub release into `bin/`. If that fails:

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_NATIVE=ON
cmake --build build --config Release -j -t llama-server
cp build/bin/llama-server /root/.cvr/llm_stress_test/cpu/bin/
```

Or set `LLAMA_SERVER=/path/to/llama-server` in `.env`.

---

## Notes

- Shared client: [`../stress_test.py`](../stress_test.py) with `--backend cpu`.
- Structured outputs use OpenAI `response_format` JSON schema (`STRUCTURED_MODE=openai`). If your build rejects it, set `STRUCTURED_MODE=prompt`.
- Do not point this client at vLLM for CPU — use [`../gpu/`](../gpu/) for GPU.
