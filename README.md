# LLM Stress Test (vLLM rephrasing)

Measure concurrent rephrase performance against a local vLLM OpenAI-compatible server.

**Default targets (single / soak / structured):** TTFT p95 `< 500ms`, per-user TPS `≥ 4`  
**Find-limit stop criteria:** TTFT p95 `> 1500ms` **or** per-user min TPS `< 4`

All settings live in [`.env`](.env). `./commands.sh` loads them automatically.

---

## Quick start

```bash
cd /root/.cvr/llm_stress_test

# 1) Client deps (uses existing gemma1bit vLLM by default)
./commands.sh setup

# 2) Review / edit config
./commands.sh show_env
# nano .env

# 3) Start server (background)
./commands.sh start_vllm_bg
./commands.sh wait_vllm

# 4) Smoke + baseline
./commands.sh health
./commands.sh smoke_plain
./commands.sh stress
```

---

## `.env` knobs

| Variable | Purpose |
|----------|---------|
| `MODEL_PATH` | HuggingFace id or local path for vLLM |
| `SERVED_MODEL_NAME` | Name clients send in `model=` |
| `VLLM_PORT` / `BASE_URL` | Server bind / client URL |
| `GPU_MEMORY_UTILIZATION` | e.g. `0.90` |
| `MAX_MODEL_LEN` | Context length (keep modest for concurrency) |
| `MAX_NUM_SEQS` | vLLM scheduler cap — set **≥** your max sweep concurrency |
| `VLLM_QUANTIZATION` | empty = bf16; `fp8` for 7B/8B on ~20GB |
| `CONCURRENCY` / `REQUESTS` | Default single-test load |
| `TTFT_MS` / `MIN_TPS` | Pass/fail budget for single tests |
| `SWEEP_*` / `STOP_*` | Find-limit ramp + stop rules |
| `SUSTAINED_*` | Sustained multi-wave test |
| `HF_TOKEN` | Required for gated models (Gemma / Llama) |

After changing **model or server flags**, restart:

```bash
./commands.sh stop_vllm
./commands.sh start_vllm_bg
./commands.sh wait_vllm
```

---

## All commands

### Lifecycle

| Command | What it does |
|---------|----------------|
| `./commands.sh setup` | Create `.venv`, install `httpx`, verify vLLM |
| `./commands.sh show_env` | Print effective config |
| `./commands.sh start_vllm` | Start vLLM in **foreground** |
| `./commands.sh start_vllm_bg` | Start vLLM in **background** (`vllm.log`, `vllm.pid`) |
| `./commands.sh wait_vllm [secs]` | Block until `/v1/models` is up (default 600s) |
| `./commands.sh stop_vllm` | Stop background server |
| `./commands.sh health` | List served models |
| `./commands.sh smoke_plain` | One plain rephrase request |
| `./commands.sh smoke_structured` | One `guided_json` rephrase |
| `./commands.sh run_all` | setup → start_bg → wait → stress |

### Stress tests

| Command | What it does | Output |
|---------|--------------|--------|
| `./commands.sh stress` | Fixed concurrency from `.env` | `stress_results_<N>c.json` |
| `./commands.sh stress_soak` | Same concurrency, 5× requests | `stress_results_<N>c_soak.json` |
| `./commands.sh stress_structured` | Fixed concurrency + JSON schema | `stress_results_<N>c_structured.json` |
| `./commands.sh stress_find_limit` | **Ramp users** until TTFT > 1500ms or TPS < 4 | `stress_results_find_limit.json` |
| `./commands.sh stress_sustained` | Many waves at `SUSTAINED_CONCURRENCY` | `stress_results_sustained_<N>c.json` |

---

## Finding the concurrency limit

```bash
# Ensure MAX_NUM_SEQS in .env is high enough (e.g. 256), then restart once
./commands.sh stop_vllm && ./commands.sh start_vllm_bg && ./commands.sh wait_vllm

./commands.sh stress_find_limit
```

Sweep starts at `SWEEP_START`, steps by `SWEEP_STEP`, up to `SWEEP_MAX`.  
Stops when **TTFT p95 > `STOP_TTFT_MS` (1500)** or **min per-user TPS < `STOP_MIN_TPS` (4)**.

Each line prints:

```text
c=  40  ttft_p95=   420.1ms  tps_min=  18.2  tps_avg=  22.1  agg_tps=  880  err%=0.0
       cpu=12.5/45.0%  gpu=88.0/98.0%  vram=17.2/17.4GB  ram=24.1/25.0GB
```

- `tps_min` / `tps_avg` = **per concurrent user**
- `agg_tps` = total system throughput
- Resource line shows **avg/max** CPU%, GPU%, VRAM, and system RAM during that level
- Full min/avg/max for CPU, GPU, VRAM, RAM (and GPU temp) are in the JSON under `system_load`

---

## Switch to 8B FP8 (when GPU is free + HF token set)

In `.env`:

```bash
MODEL_PATH=meta-llama/Llama-3.1-8B-Instruct
SERVED_MODEL_NAME=Llama-3.1-8B-Instruct
VLLM_QUANTIZATION=fp8
GPU_MEMORY_UTILIZATION=0.90
MAX_MODEL_LEN=8192
MAX_NUM_SEQS=256
HF_TOKEN=hf_your_token_here
```

Then:

```bash
./commands.sh stop_vllm
./commands.sh start_vllm_bg
./commands.sh wait_vllm
./commands.sh stress_find_limit
```

---

## Notes

- Stress clients auto-detect the **currently served** model name (avoids 404 if `.env` drifts). Force the `.env` name with `SERVED_MODEL_NAME_FORCE=1`.
- Default model is open **`Qwen/Qwen2.5-3B-Instruct`** (no HF gate). Gemma/Llama need `HF_TOKEN`.
- Logs: `vllm.log`. Results: `stress_results_*.json`.
