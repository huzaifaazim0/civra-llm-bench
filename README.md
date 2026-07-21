# LLM Stress Test

Concurrent rephrase stress tests against a local OpenAI-compatible LLM server.

| Path | Engine | Hardware |
|------|--------|----------|
| [`gpu/`](gpu/) | **vLLM** | CUDA GPU |
| [`cpu/`](cpu/) | **llama.cpp** `llama-server` | CPU (all cores/threads) |

Shared client: [`stress_test.py`](stress_test.py) (TTFT, per-user TPS, system load, find-limit sweep).

## Quick start — GPU

```bash
cd gpu
./commands.sh setup
./commands.sh start_vllm_bg && ./commands.sh wait_vllm
./commands.sh stress
# or: ./commands.sh stress_find_limit
```

Default budgets: TTFT p95 `< 500ms`, per-user TPS `≥ 4`. See [`gpu/README.md`](gpu/README.md).

## Quick start — CPU

```bash
cd cpu
./commands.sh setup
./commands.sh download_model
./commands.sh start_llama_bg && ./commands.sh wait_llama
./commands.sh show_env    # threads, parallel, cores, RAM
./commands.sh stress
# or: ./commands.sh stress_find_limit
```

Defaults use **all logical cores** (`nproc`) for `--threads` / `--threads-batch`.  
CPU SLOs are looser (TTFT / TPS). See [`cpu/README.md`](cpu/README.md).

## Ports

- GPU vLLM: `8000`
- CPU llama-server: `8010`

Both can run at once if you have GPU + CPU capacity.

## Shared deps

```bash
# created by either setup command
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
