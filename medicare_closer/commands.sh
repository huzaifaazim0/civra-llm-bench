#!/usr/bin/env bash
# Medicare closer correctness + stress + interactive against OpenAI-compatible LLM (GPU vLLM).
#
#   ./commands.sh interactive
#   ./commands.sh correctness
#   ./commands.sh correctness_freeform
#   ./commands.sh stress_turns
#   ./commands.sh bakeoff
#
# Start the GPU server first:
#   cd ../gpu && ./commands.sh start_vllm_bg && ./commands.sh wait_vllm

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
GPU_ENV="${REPO_ROOT}/gpu/.env"
cd "$ROOT"

load_env_file() {
  local env_file="$1"
  local override="${2:-0}"
  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    local key="${line%%=*}"
    local val="${line#*=}"
    key="$(echo "$key" | xargs)"
    [[ -z "$key" ]] && continue
    if [[ "$override" == "1" ]] || [[ -z "${!key+x}" ]]; then
      export "$key=$val"
    fi
  done < "$env_file"
}

load_env_file "$GPU_ENV" 0
load_env_file "${ENV_FILE:-$ROOT/.env}" 1

BASE_URL="${BASE_URL:-http://127.0.0.1:${VLLM_PORT:-8000}}"
export BASE_URL
export MODEL="${MODEL:-${SERVED_MODEL_NAME:-}}"
export AGENT_NAME="${AGENT_NAME:-Alex}"
export BROKER_NAME="${BROKER_NAME:-Summit Senior Advisors}"
export STATE_NAME="${STATE_NAME:-Texas}"
export EFFECTIVE_DATE="${EFFECTIVE_DATE:-January 1, 2026}"
export STRUCTURED_MODE="${STRUCTURED_MODE:-vllm}"
export PROMPT_STYLE="${PROMPT_STYLE:-auto}"
export MAX_TOKENS="${MAX_TOKENS:-512}"
export TEMPERATURE="${TEMPERATURE:-0.1}"
export INTERACTIVE_TEMPERATURE="${INTERACTIVE_TEMPERATURE:-0.6}"
export INTERACTIVE_TARGET_TTFT_MS="${INTERACTIVE_TARGET_TTFT_MS:-${INTERACTIVE_TARGET_MS:-555}}"
export INTERACTIVE_MAX_TOKENS="${INTERACTIVE_MAX_TOKENS:-120}"
export INTERACTIVE_CONTEXT_TURNS="${INTERACTIVE_CONTEXT_TURNS:-6}"
export CONTEXT_TURNS="${CONTEXT_TURNS:-8}"
export USE_CONTROLLER="${USE_CONTROLLER:-1}"
export USE_LLM_UNDERSTAND="${USE_LLM_UNDERSTAND:-0}"
export CONCURRENCY="${CONCURRENCY:-5}"
export REQUESTS="${REQUESTS:-10}"
export SESSIONS="${SESSIONS:-5}"
export SWEEP_START="${SWEEP_START:-1}"
export SWEEP_MAX="${SWEEP_MAX:-40}"
export SWEEP_STEP="${SWEEP_STEP:-5}"
export SWEEP_WAVES="${SWEEP_WAVES:-1}"
export STOP_TTFT_MS="${STOP_TTFT_MS:-2500}"
export STOP_MIN_TPS="${STOP_MIN_TPS:-3}"
export MAX_ERROR_RATE="${MAX_ERROR_RATE:-0.08}"

activate_client() {
  # shellcheck disable=SC1091
  if [[ -f "${REPO_ROOT}/.venv/bin/activate" ]]; then
    source "${REPO_ROOT}/.venv/bin/activate"
  fi
}

run_python() {
  activate_client
  python3 closer_stress.py "$@"
}

cmd="${1:-}"
shift || true

case "$cmd" in
  setup)
    if [[ ! -d "${REPO_ROOT}/.venv" ]]; then
      python3 -m venv "${REPO_ROOT}/.venv"
    fi
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.venv/bin/activate"
    pip install -q -r "${REPO_ROOT}/requirements.txt"
    if [[ ! -f "$ROOT/.env" ]]; then
      cp "$ROOT/.env.example" "$ROOT/.env"
      echo "Created $ROOT/.env from .env.example"
    fi
    echo "Setup OK. Start GPU vLLM via ../gpu/commands.sh then run correctness or interactive."
    ;;
  show_env)
    echo "BASE_URL=$BASE_URL"
    echo "MODEL=${MODEL:-"(auto)"}"
    echo "STRUCTURED_MODE=$STRUCTURED_MODE"
    echo "AGENT_NAME=$AGENT_NAME BROKER_NAME=$BROKER_NAME STATE_NAME=$STATE_NAME"
    echo "MAX_TOKENS=$MAX_TOKENS CONTEXT_TURNS=$CONTEXT_TURNS"
    echo "CONCURRENCY=$CONCURRENCY REQUESTS=$REQUESTS SESSIONS=$SESSIONS"
    ;;
  interactive)
    run_python interactive \
      --base-url "$BASE_URL" \
      ${MODEL:+--model "$MODEL"} \
      --structured-mode "$STRUCTURED_MODE" \
      --prompt-style "$PROMPT_STYLE" \
      --agent-name "$AGENT_NAME" \
      --broker-name "$BROKER_NAME" \
      --state-name "$STATE_NAME" \
      --effective-date "$EFFECTIVE_DATE" \
      --max-tokens "${INTERACTIVE_MAX_TOKENS:-$MAX_TOKENS}" \
      --temperature "${INTERACTIVE_TEMPERATURE}" \
      --context-turns "${INTERACTIVE_CONTEXT_TURNS:-$CONTEXT_TURNS}" \
      "$@"
    ;;
  correctness)
    run_python correctness \
      --base-url "$BASE_URL" \
      ${MODEL:+--model "$MODEL"} \
      --structured-mode "$STRUCTURED_MODE" \
      --prompt-style "$PROMPT_STYLE" \
      --agent-name "$AGENT_NAME" \
      --broker-name "$BROKER_NAME" \
      --state-name "$STATE_NAME" \
      --effective-date "$EFFECTIVE_DATE" \
      --max-tokens "$MAX_TOKENS" \
      --temperature "$TEMPERATURE" \
      --context-turns "$CONTEXT_TURNS"
    ;;
  correctness_freeform)
    run_python correctness_freeform \
      --base-url "$BASE_URL" \
      ${MODEL:+--model "$MODEL"} \
      --prompt-style "$PROMPT_STYLE" \
      --agent-name "$AGENT_NAME" \
      --broker-name "$BROKER_NAME" \
      --state-name "$STATE_NAME" \
      --effective-date "$EFFECTIVE_DATE" \
      --max-tokens "$MAX_TOKENS" \
      --temperature "$TEMPERATURE" \
      --context-turns "$CONTEXT_TURNS"
    ;;
  stress_turns)
    run_python stress_turns \
      --base-url "$BASE_URL" \
      ${MODEL:+--model "$MODEL"} \
      --structured-mode "$STRUCTURED_MODE" \
      --prompt-style "$PROMPT_STYLE" \
      --agent-name "$AGENT_NAME" \
      --broker-name "$BROKER_NAME" \
      --state-name "$STATE_NAME" \
      --effective-date "$EFFECTIVE_DATE" \
      --max-tokens "$MAX_TOKENS" \
      --temperature "$TEMPERATURE" \
      --concurrency "$CONCURRENCY" \
      --requests "$REQUESTS"
    ;;
  stress_sessions)
    run_python stress_sessions \
      --base-url "$BASE_URL" \
      ${MODEL:+--model "$MODEL"} \
      --structured-mode "$STRUCTURED_MODE" \
      --prompt-style "$PROMPT_STYLE" \
      --agent-name "$AGENT_NAME" \
      --broker-name "$BROKER_NAME" \
      --state-name "$STATE_NAME" \
      --effective-date "$EFFECTIVE_DATE" \
      --max-tokens "$MAX_TOKENS" \
      --temperature "$TEMPERATURE" \
      --context-turns "$CONTEXT_TURNS" \
      --concurrency "$CONCURRENCY" \
      --sessions "$SESSIONS"
    ;;
  find_limit)
    run_python find_limit \
      --base-url "$BASE_URL" \
      ${MODEL:+--model "$MODEL"} \
      --structured-mode "$STRUCTURED_MODE" \
      --prompt-style "$PROMPT_STYLE" \
      --agent-name "$AGENT_NAME" \
      --broker-name "$BROKER_NAME" \
      --state-name "$STATE_NAME" \
      --effective-date "$EFFECTIVE_DATE" \
      --max-tokens "$MAX_TOKENS" \
      --temperature "$TEMPERATURE" \
      --context-turns "$CONTEXT_TURNS" \
      --sweep-start "$SWEEP_START" \
      --sweep-max "$SWEEP_MAX" \
      --sweep-step "$SWEEP_STEP" \
      --sweep-waves "$SWEEP_WAVES" \
      --stop-ttft-ms "$STOP_TTFT_MS" \
      --stop-min-tps "$STOP_MIN_TPS" \
      --max-error-rate "$MAX_ERROR_RATE"
    ;;
  bakeoff)
    exec "$ROOT/run_bakeoff.sh" "$@"
    ;;
  help|-h|--help|"")
    cat <<'EOF'
Usage: ./commands.sh <command>

  setup                  Create parent venv + local .env
  show_env               Print effective settings
  interactive            Terminal chat with closer (freeform; add --structured --debug)
  correctness            Structured JSON multi-turn flow checks
  correctness_freeform   Plain-speech runs + transcripts + judge pack for ChatGPT
  stress_turns           Concurrent single-turn closer JSON stress
  stress_sessions        Concurrent full multi-turn session stress
  find_limit             Ramp session concurrency until SLO / error breach
  bakeoff                Gemma-4-E4B + Qwen2.5-7B correctness+stress bake-off

Prereq: GPU vLLM on BASE_URL (default http://127.0.0.1:8000)
  cd ../gpu && ./commands.sh start_vllm_bg && ./commands.sh wait_vllm
EOF
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    echo "Run: ./commands.sh help" >&2
    exit 1
    ;;
esac
