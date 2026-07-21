# Medicare Closer LLM Stress & Correctness

Multi-turn Medicare **closer** voice-agent tests against a local OpenAI-compatible LLM (GPU vLLM from [`../gpu`](../gpu)).

Outbound licensed agent: review current coverage vs 2026 options, handle side topics, enroll via voice signature when beneficial — or close correctly (optimal plan / employer conflict / DNC / callback).

## Modes

| Mode | Purpose |
|------|---------|
| **interactive** | Talk to the agent in the terminal (freeform by default) |
| **correctness** | Structured JSON auto-score across 15 full-flow scenarios |
| **correctness_freeform** | Plain-speech runs → transcripts + judge pack for ChatGPT |
| **stress_turns / stress_sessions / find_limit** | Concurrency / latency stress |
| **bakeoff** | `google/gemma-4-E4B-it` + `Qwen/Qwen2.5-7B-Instruct` |

## Fixed plan catalog

| ID | Plan |
|----|------|
| `giveback_ppo` | Part B giveback PPO (~$103) |
| `otc_zero` | $0 premium + $44 OTC |
| `dual_food_snp` | Dual C-SNP food/utility U-card |

## Quick start

```bash
cd ../gpu && ./commands.sh start_vllm_bg && ./commands.sh wait_vllm

cd ../medicare_closer
./commands.sh setup
./commands.sh interactive
./commands.sh correctness
./commands.sh correctness_freeform   # then paste judge/JUDGE_PROMPT.md + a transcript into ChatGPT
./commands.sh bakeoff
```

Interactive with structured JSON + debug:

```bash
./commands.sh interactive --structured --debug
```

## Config

Copy [`.env.example`](.env.example) → `.env`. Inherits [`../gpu/.env`](../gpu/.env) for `BASE_URL` / served model.

Notes:
- `PROMPT_STYLE=auto` resolves to **compact** (closer multi-turn is long; full prompt can exceed a 4k context window).
- Defaults: `MAX_TOKENS=384`, `CONTEXT_TURNS=4`. Raise both if your vLLM `max_model_len` is 8k+.
- Interactive freeform uses `INTERACTIVE_TEMPERATURE=0.6` by default.

## Layout

```
plans.py            Fixed fake plan catalog
schema.py           JSON schema + parse/normalize
prompts.py          full / compact / freeform system prompts
flows.py            15 full multi-turn scenarios
validators.py       Schema + state-machine + expects
closer_stress.py    Harness (all modes)
report.py           JSON/MD writers
judge/              External LLM-as-judge prompt pack
commands.sh         CLI wrappers
run_bakeoff.sh      2-model bake-off
```

## Freeform scoring

1. `./commands.sh correctness_freeform`
2. Open `results/freeform_<stamp>/`
3. Copy `JUDGE_PROMPT.md` + one `<scenario>.md` into ChatGPT
4. Fill `score_template.json` with the judge JSON response

## Reports

Under [`results/`](results/):

- `closer_correctness_<model>.json` + `.md`
- `closer_freeform_<model>.json` + `.md` + `freeform_<stamp>/`
- `closer_stress_*` / `closer_find_limit_*`
- `BAKEOFF_REPORT_LATEST.md`
