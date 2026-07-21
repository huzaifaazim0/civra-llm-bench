# Medicare Fronter LLM Stress & Correctness

Multi-turn Medicare **fronter** voice-agent tests against a local OpenAI-compatible LLM (GPU vLLM from [`../gpu`](../gpu)).

Each model turn must return JSON with `message`, `state`, `next`, and `action`. The harness checks schema, state-machine rules, scripted flow expectations (including DNC / abuse), and reports **TTFT**, **TPS**, and full generation latency.

## Flow under test

1. Introduce (Sarah from Medicare) — do you have a few minutes?
2. Ask Part A and Part B
3. Ask age
4. Age ≥ 65 → transfer to licensed agent  
   Age &lt; 65 → ask disability → transfer or polite close
5. Side topics: acknowledge and re-ask current question
6. DNC / abuse: end immediately with the correct `action`

## Quick start

```bash
# 1) Start GPU server (from repo)
cd ../gpu
./commands.sh start_vllm_bg && ./commands.sh wait_vllm

# 2) Setup + run this harness
cd ../medicare_fronter
./commands.sh setup
./commands.sh correctness
./commands.sh stress_turns          # CONCURRENCY=10 REQUESTS=20
./commands.sh stress_sessions       # concurrent full conversations
./commands.sh find_limit            # ramp until TTFT/TPS/error SLO breaks
```

## Commands

| Command | Purpose |
|---------|---------|
| `correctness` | All scripted scenarios; per-turn JSON + flow validation |
| `stress_turns` | N concurrent single mid-flow turns |
| `stress_sessions` | N concurrent full multi-turn sessions |
| `find_limit` | Ramp session concurrency; report `max_stable_concurrency` |

## Config

Copy [`.env.example`](.env.example) → `.env`, or export env vars. Values also inherit from [`../gpu/.env`](../gpu/.env) (`BASE_URL`, served model name).

| Variable | Default | Meaning |
|----------|---------|---------|
| `BASE_URL` | `http://127.0.0.1:8000` | OpenAI-compatible endpoint |
| `STRUCTURED_MODE` | `vllm` | `vllm` / `openai` / `prompt` JSON enforcement |
| `AGENT_NAME` | `Sarah` | Spoken agent name |
| `MAX_ERROR_RATE` | `0.05` | Find-limit stop on flow/schema errors |
| `STOP_TTFT_MS` | `1500` | Find-limit TTFT p95 stop |
| `STOP_MIN_TPS` | `4` | Find-limit min TPS stop |

## Reports

Written under [`results/`](results/):

- `fronter_correctness_<model>.json` + `.md` — pass/fail by scenario, error taxonomy, latency
- `fronter_stress_turns_<model>_<Nc>.json` + `.md`
- `fronter_stress_sessions_<model>_<Nc>.json` + `.md`
- `fronter_find_limit_<model>.json` + `.md` — concurrency sweep + max stable N

## Layout

```
prompts.py          System prompt + context trim
schema.py           JSON schema + parse helpers
flows.py            Scripted scenarios + stress contexts
validators.py       Schema / state-machine / expect checks
fronter_stress.py   Async harness (all modes)
report.py           JSON + Markdown writers
commands.sh         CLI wrappers
```

## Multi-model bake-off

```bash
./commands.sh bakeoff
# or: MODELS="Qwen/Qwen2.5-3B-Instruct google/gemma-4-E4B-it" ./run_bakeoff.sh
```

Latest report: [`results/BAKEOFF_REPORT_LATEST.md`](results/BAKEOFF_REPORT_LATEST.md)
