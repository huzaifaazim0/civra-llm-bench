#!/usr/bin/env bash
# GPU (vLLM) concurrent rephrasing stress tests.
# All settings come from .env (override with exports if needed).
#
#   ./commands.sh setup
#   ./commands.sh start_vllm_bg
#   ./commands.sh wait_vllm
#   ./commands.sh stress
#   ./commands.sh stress_find_limit

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
cd "$ROOT"

# Load .env without clobbering variables already set in the shell
load_env() {
  local env_file="${ENV_FILE:-$ROOT/.env}"
  if [[ ! -f "$env_file" ]]; then
    echo "Missing $env_file — copy .env.example or create one." >&2
    exit 1
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    local key="${line%%=*}"
    local val="${line#*=}"
    key="$(echo "$key" | xargs)"
    [[ -z "$key" ]] && continue
    if [[ -z "${!key+x}" ]]; then
      export "$key=$val"
    fi
  done < "$env_file"
}

load_env

# Prefer an existing vLLM install unless overridden.
DEFAULT_VLLM_VENV="${REPO_ROOT}/../gemma1bit/venv"
VLLM_VENV="${VLLM_VENV:-$DEFAULT_VLLM_VENV}"
if [[ -x "${VLLM_VENV}/bin/python" ]]; then
  VLLM_PYTHON="${VLLM_PYTHON:-${VLLM_VENV}/bin/python}"
else
  VLLM_PYTHON="${VLLM_PYTHON:-python3}"
fi

MODEL_PATH="${MODEL_PATH:-Qwen/Qwen2.5-3B-Instruct}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-Qwen2.5-3B-Instruct}"
VLLM_HOST="${VLLM_HOST:-0.0.0.0}"
VLLM_PORT="${VLLM_PORT:-8000}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-4096}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-256}"
VLLM_QUANTIZATION="${VLLM_QUANTIZATION:-}"
# AWQ requires float16; default bf16 for non-quant / fp8.
DTYPE="${DTYPE:-bfloat16}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${VLLM_PORT}}"
CONCURRENCY="${CONCURRENCY:-20}"
REQUESTS="${REQUESTS:-20}"
TTFT_MS="${TTFT_MS:-500}"
MIN_TPS="${MIN_TPS:-4}"
MAX_TOKENS="${MAX_TOKENS:-64}"
TEMPERATURE="${TEMPERATURE:-0.2}"
SWEEP_START="${SWEEP_START:-1}"
SWEEP_MAX="${SWEEP_MAX:-200}"
SWEEP_STEP="${SWEEP_STEP:-5}"
SWEEP_WAVES="${SWEEP_WAVES:-1}"
STOP_TTFT_MS="${STOP_TTFT_MS:-1500}"
STOP_MIN_TPS="${STOP_MIN_TPS:-4}"
SUSTAINED_CONCURRENCY="${SUSTAINED_CONCURRENCY:-40}"
SUSTAINED_WAVES="${SUSTAINED_WAVES:-10}"
VLLM_LOG="${VLLM_LOG:-${ROOT}/vllm.log}"
VLLM_PID_FILE="${VLLM_PID_FILE:-${ROOT}/vllm.pid}"

activate_client() {
  # shellcheck disable=SC1091
  [[ -f "${REPO_ROOT}/.venv/bin/activate" ]] && source "${REPO_ROOT}/.venv/bin/activate"
}

server_config_json() {
  python3 -c '
import json, os
print(json.dumps({
  "engine": "vllm",
  "model_path": os.environ.get("MODEL_PATH", ""),
  "served_model_name": os.environ.get("SERVED_MODEL_NAME", ""),
  "port": int(os.environ.get("VLLM_PORT", "8000")),
  "gpu_memory_utilization": float(os.environ.get("GPU_MEMORY_UTILIZATION", "0.9")),
  "max_model_len": int(os.environ.get("MAX_MODEL_LEN", "4096")),
  "max_num_seqs": int(os.environ.get("MAX_NUM_SEQS", "256")),
  "quantization": os.environ.get("VLLM_QUANTIZATION") or None,
  "dtype": os.environ.get("DTYPE", "bfloat16"),
}))
'
}

# Use the model name actually served by vLLM (avoids 404 when .env drifts).
resolve_served_model() {
  if [[ "${SERVED_MODEL_NAME_FORCE:-}" == "1" ]]; then
    return 0
  fi
  local detected
  detected="$(curl -sf "$BASE_URL/v1/models" 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["data"][0]["id"] if d.get("data") else "")' 2>/dev/null || true)"
  if [[ -n "$detected" ]]; then
    if [[ "$detected" != "$SERVED_MODEL_NAME" ]]; then
      echo "Using served model: $detected (set SERVED_MODEL_NAME_FORCE=1 to keep .env name)" >&2
    fi
    SERVED_MODEL_NAME="$detected"
  fi
}

stress_common_args() {
  local cfg
  cfg="$(server_config_json)"
  printf '%s\n' \
    --backend gpu \
    --structured-mode vllm \
    --server-config "$cfg" \
    --base-url "$BASE_URL" \
    --model "$SERVED_MODEL_NAME" \
    --max-tokens "$MAX_TOKENS" \
    --temperature "$TEMPERATURE" \
    --ttft-ms "$TTFT_MS" \
    --min-tps "$MIN_TPS" \
    --stop-ttft-ms "$STOP_TTFT_MS" \
    --stop-min-tps "$STOP_MIN_TPS"
}

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
cmd_setup() {
  python3 -m venv "${REPO_ROOT}/.venv"
  activate_client
  pip install -U pip
  pip install -r "${REPO_ROOT}/requirements.txt"

  if ! "$VLLM_PYTHON" -c "import vllm" >/dev/null 2>&1; then
    echo "vLLM not found at $VLLM_PYTHON" >&2
    echo "Install with: pip install -U vllm  (in $VLLM_VENV or this .venv)" >&2
    exit 1
  fi

  echo "Client deps ready."
  echo "vLLM: $("$VLLM_PYTHON" -c 'import vllm; print(vllm.__version__)')"
  echo "Python: $VLLM_PYTHON"
  echo "Model:  $MODEL_PATH (served as $SERVED_MODEL_NAME)"
}

vllm_common_args() {
  local -a args=(
    --model "$MODEL_PATH"
    --served-model-name "$SERVED_MODEL_NAME"
    --dtype "$DTYPE"
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
    --max-model-len "$MAX_MODEL_LEN"
    --enable-chunked-prefill
    --enable-prefix-caching
    --max-num-seqs "$MAX_NUM_SEQS"
    --host "$VLLM_HOST"
    --port "$VLLM_PORT"
  )
  if [[ -n "$VLLM_QUANTIZATION" ]]; then
    args+=(--quantization "$VLLM_QUANTIZATION")
  fi
  printf '%s\n' "${args[@]}"
}

cmd_start_vllm() {
  if [[ -n "${HF_TOKEN:-}" ]]; then
    export HF_TOKEN
    export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
  fi
  echo "Starting vLLM: model=$MODEL_PATH served=$SERVED_MODEL_NAME port=$VLLM_PORT max_num_seqs=$MAX_NUM_SEQS"
  mapfile -t vllm_args < <(vllm_common_args)
  exec "$VLLM_PYTHON" -m vllm.entrypoints.openai.api_server "${vllm_args[@]}"
}

cmd_start_vllm_bg() {
  if [[ -f "$VLLM_PID_FILE" ]] && kill -0 "$(cat "$VLLM_PID_FILE")" 2>/dev/null; then
    echo "vLLM already running (pid $(cat "$VLLM_PID_FILE"))"
    return 0
  fi
  if ! "$VLLM_PYTHON" -c "import vllm" >/dev/null 2>&1; then
    echo "vLLM missing. Run: ./commands.sh setup" >&2
    exit 1
  fi
  if [[ -n "${HF_TOKEN:-}" ]]; then
    export HF_TOKEN
    export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
  fi
  echo "Starting vLLM in background -> $VLLM_LOG"
  echo "  model=$MODEL_PATH served=$SERVED_MODEL_NAME max_num_seqs=$MAX_NUM_SEQS"
  mapfile -t vllm_args < <(vllm_common_args)
  nohup "$VLLM_PYTHON" -m vllm.entrypoints.openai.api_server \
    "${vllm_args[@]}" >"$VLLM_LOG" 2>&1 &
  echo $! >"$VLLM_PID_FILE"
  echo "pid $(cat "$VLLM_PID_FILE")"
}

cmd_wait_vllm() {
  local timeout="${1:-600}"
  local elapsed=0
  echo "Waiting for $BASE_URL/v1/models (timeout ${timeout}s)..."
  while (( elapsed < timeout )); do
    if curl -sf "$BASE_URL/v1/models" >/dev/null 2>&1; then
      echo "vLLM is ready."
      cmd_health
      return 0
    fi
    if [[ -f "$VLLM_PID_FILE" ]] && ! kill -0 "$(cat "$VLLM_PID_FILE")" 2>/dev/null; then
      echo "vLLM process exited. Last log lines:" >&2
      tail -n 40 "$VLLM_LOG" >&2 || true
      return 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "Timed out waiting for vLLM." >&2
  tail -n 40 "$VLLM_LOG" >&2 || true
  return 1
}

cmd_stop_vllm() {
  if [[ -f "$VLLM_PID_FILE" ]]; then
    local pid
    pid="$(cat "$VLLM_PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      echo "Stopped vLLM (pid $pid)"
    fi
    rm -f "$VLLM_PID_FILE"
  else
    echo "No pid file at $VLLM_PID_FILE"
  fi
}

cmd_start_vllm_bf16() {
  VLLM_QUANTIZATION=""
  cmd_start_vllm
}

cmd_health() {
  curl -sS "$BASE_URL/v1/models" | python3 -m json.tool
}

cmd_show_env() {
  local logical physical ram_gb
  logical="$(nproc 2>/dev/null || echo "?")"
  physical="$("${REPO_ROOT}/.venv/bin/python" -c 'import psutil; print(psutil.cpu_count(logical=False) or "?")' 2>/dev/null || echo "?")"
  ram_gb="$("${REPO_ROOT}/.venv/bin/python" -c 'import psutil; print(round(psutil.virtual_memory().total/1024**3,1))' 2>/dev/null || echo "?")"
  cat <<EOF
backend=gpu (vLLM)
MODEL_PATH=$MODEL_PATH
SERVED_MODEL_NAME=$SERVED_MODEL_NAME
BASE_URL=$BASE_URL
VLLM_PORT=$VLLM_PORT
GPU_MEMORY_UTILIZATION=$GPU_MEMORY_UTILIZATION
MAX_MODEL_LEN=$MAX_MODEL_LEN
MAX_NUM_SEQS=$MAX_NUM_SEQS
VLLM_QUANTIZATION=${VLLM_QUANTIZATION:-<none>}
DTYPE=$DTYPE
CONCURRENCY=$CONCURRENCY
TTFT_MS=$TTFT_MS MIN_TPS=$MIN_TPS
STOP_TTFT_MS=$STOP_TTFT_MS STOP_MIN_TPS=$STOP_MIN_TPS
SWEEP_START=$SWEEP_START SWEEP_MAX=$SWEEP_MAX SWEEP_STEP=$SWEEP_STEP
SUSTAINED_CONCURRENCY=$SUSTAINED_CONCURRENCY SUSTAINED_WAVES=$SUSTAINED_WAVES
VLLM_PYTHON=$VLLM_PYTHON
host_logical_cores=$logical host_physical_cores=$physical ram_total_gb=$ram_gb
EOF
}

# ---------------------------------------------------------------------------
# Stress tests
# ---------------------------------------------------------------------------
cmd_stress() {
  resolve_served_model
  activate_client
  mapfile -t common < <(stress_common_args)
  python "${REPO_ROOT}/stress_test.py" \
    --mode single \
    "${common[@]}" \
    --concurrency "$CONCURRENCY" \
    --requests "$REQUESTS" \
    --output "stress_results_${CONCURRENCY}c.json"
}

cmd_stress_soak() {
  resolve_served_model
  activate_client
  mapfile -t common < <(stress_common_args)
  python "${REPO_ROOT}/stress_test.py" \
    --mode single \
    "${common[@]}" \
    --concurrency "$CONCURRENCY" \
    --requests "$((CONCURRENCY * 5))" \
    --output "stress_results_${CONCURRENCY}c_soak.json"
}

cmd_stress_structured() {
  resolve_served_model
  activate_client
  mapfile -t common < <(stress_common_args)
  local tok="$MAX_TOKENS"
  if (( tok < 128 )); then
    tok=128
  fi
  python "${REPO_ROOT}/stress_test.py" \
    --mode single \
    "${common[@]}" \
    --concurrency "$CONCURRENCY" \
    --requests "$REQUESTS" \
    --max-tokens "$tok" \
    --structured \
    --output "stress_results_${CONCURRENCY}c_structured.json"
}

cmd_stress_find_limit() {
  resolve_served_model
  activate_client
  mapfile -t common < <(stress_common_args)
  python "${REPO_ROOT}/stress_test.py" \
    --mode sweep \
    "${common[@]}" \
    --sweep-start "$SWEEP_START" \
    --sweep-max "$SWEEP_MAX" \
    --sweep-step "$SWEEP_STEP" \
    --sweep-waves "$SWEEP_WAVES" \
    --output "stress_results_find_limit.json"
}

cmd_stress_sustained() {
  resolve_served_model
  activate_client
  mapfile -t common < <(stress_common_args)
  python "${REPO_ROOT}/stress_test.py" \
    --mode sustained \
    "${common[@]}" \
    --concurrency "$SUSTAINED_CONCURRENCY" \
    --waves "$SUSTAINED_WAVES" \
    --output "stress_results_sustained_${SUSTAINED_CONCURRENCY}c.json"
}

cmd_smoke_plain() {
  resolve_served_model
  curl -sS "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"$SERVED_MODEL_NAME\",
      \"messages\": [
        {\"role\": \"system\", \"content\": \"Rephrase clearly. No commentary.\"},
        {\"role\": \"user\", \"content\": \"Rephrase this: The quick brown fox jumps over the lazy dog.\"}
      ],
      \"max_tokens\": 64,
      \"temperature\": 0.2
    }" | python3 -m json.tool
}

cmd_smoke_structured() {
  resolve_served_model
  curl -sS "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"$SERVED_MODEL_NAME\",
      \"messages\": [
        {\"role\": \"system\", \"content\": \"Return ONLY JSON with keys original and rephrased.\"},
        {\"role\": \"user\", \"content\": \"Rephrase this: The quick brown fox jumps over the lazy dog.\"}
      ],
      \"max_tokens\": 128,
      \"temperature\": 0.2,
      \"structured_outputs\": {
        \"json\": {
          \"type\": \"object\",
          \"properties\": {
            \"original\": {\"type\": \"string\"},
            \"rephrased\": {\"type\": \"string\"}
          },
          \"required\": [\"original\", \"rephrased\"]
        }
      }
    }" | python3 -m json.tool
}

cmd_run_all() {
  cmd_setup
  cmd_start_vllm_bg
  cmd_wait_vllm 600
  cmd_stress
}

usage() {
  cat <<EOF
Usage: ./commands.sh <command>

GPU (vLLM) stress tests. Config: edit .env then restart server if model/flags change.
  ./commands.sh show_env

Lifecycle:
  setup                 Create client venv + install httpx
  show_env              Print effective config from .env
  start_vllm            Launch vLLM in foreground (uses .env)
  start_vllm_bg         Launch vLLM in background
  wait_vllm [secs]      Wait until /v1/models responds
  stop_vllm             Stop background vLLM
  health                GET /v1/models
  smoke_plain           Single plain rephrase
  smoke_structured      Single guided_json rephrase
  run_all               setup + start_bg + wait + stress

Stress tests:
  stress                Fixed concurrency (CONCURRENCY from .env)
  stress_soak           Same concurrency, 5x requests
  stress_structured     Fixed concurrency + guided_json
  stress_find_limit     Ramp concurrency until TTFT>STOP_TTFT_MS or tps<STOP_MIN_TPS
  stress_sustained      Many waves at SUSTAINED_CONCURRENCY

Typical limit hunt:
  ./commands.sh stop_vllm
  ./commands.sh start_vllm_bg
  ./commands.sh wait_vllm
  ./commands.sh stress_find_limit
EOF
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    setup) cmd_setup ;;
    show_env) cmd_show_env ;;
    start_vllm) cmd_start_vllm ;;
    start_vllm_bg) cmd_start_vllm_bg ;;
    wait_vllm) cmd_wait_vllm "${2:-600}" ;;
    stop_vllm) cmd_stop_vllm ;;
    start_vllm_bf16) cmd_start_vllm_bf16 ;;
    run_all) cmd_run_all ;;
    health) cmd_health ;;
    smoke_plain) cmd_smoke_plain ;;
    smoke_structured) cmd_smoke_structured ;;
    stress) cmd_stress ;;
    stress_soak) cmd_stress_soak ;;
    stress_structured) cmd_stress_structured ;;
    stress_find_limit) cmd_stress_find_limit ;;
    stress_sustained) cmd_stress_sustained ;;
    ""|-h|--help|help) usage ;;
    *)
      echo "Unknown command: $cmd" >&2
      usage
      exit 1
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
