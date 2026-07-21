#!/usr/bin/env bash
# CPU (llama.cpp llama-server) concurrent rephrasing stress tests.
# Uses all CPU cores by default. Same stress scenarios as the GPU path.
#
#   ./commands.sh setup
#   ./commands.sh download_model
#   ./commands.sh start_llama_bg
#   ./commands.sh wait_llama
#   ./commands.sh stress
#   ./commands.sh stress_find_limit

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
cd "$ROOT"

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

MODEL_FILE="${MODEL_FILE:-Qwen2.5-1.5B-Instruct-Q4_K_M.gguf}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-Qwen2.5-1.5B-Instruct-Q4_K_M}"
HF_GGUF_REPO="${HF_GGUF_REPO:-Qwen/Qwen2.5-1.5B-Instruct-GGUF}"
HF_GGUF_FILE="${HF_GGUF_FILE:-qwen2.5-1.5b-instruct-q4_k_m.gguf}"
LLAMA_HOST="${LLAMA_HOST:-0.0.0.0}"
LLAMA_PORT="${LLAMA_PORT:-8010}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${LLAMA_PORT}}"
LLAMA_PARALLEL="${LLAMA_PARALLEL:-8}"
LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-4096}"
LLAMA_BATCH_SIZE="${LLAMA_BATCH_SIZE:-512}"
LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-0}"
CONCURRENCY="${CONCURRENCY:-4}"
REQUESTS="${REQUESTS:-4}"
TTFT_MS="${TTFT_MS:-2000}"
MIN_TPS="${MIN_TPS:-1}"
MAX_TOKENS="${MAX_TOKENS:-64}"
TEMPERATURE="${TEMPERATURE:-0.2}"
STRUCTURED_MODE="${STRUCTURED_MODE:-openai}"
SWEEP_START="${SWEEP_START:-1}"
SWEEP_MAX="${SWEEP_MAX:-32}"
SWEEP_STEP="${SWEEP_STEP:-2}"
SWEEP_WAVES="${SWEEP_WAVES:-1}"
STOP_TTFT_MS="${STOP_TTFT_MS:-8000}"
STOP_MIN_TPS="${STOP_MIN_TPS:-1}"
SUSTAINED_CONCURRENCY="${SUSTAINED_CONCURRENCY:-4}"
SUSTAINED_WAVES="${SUSTAINED_WAVES:-10}"
LLAMA_LOG="${LLAMA_LOG:-${ROOT}/llama.log}"
LLAMA_PID_FILE="${LLAMA_PID_FILE:-${ROOT}/llama.pid}"
MODELS_DIR="${MODELS_DIR:-${ROOT}/models}"
BIN_DIR="${BIN_DIR:-${ROOT}/bin}"

# Resolve threads: empty = all logical cores
NPROC="$(nproc 2>/dev/null || echo 1)"
if [[ -z "${LLAMA_THREADS:-}" ]]; then
  LLAMA_THREADS="$NPROC"
fi
if [[ -z "${LLAMA_THREADS_BATCH:-}" ]]; then
  LLAMA_THREADS_BATCH="$LLAMA_THREADS"
fi

resolve_model_path() {
  if [[ -f "$MODEL_FILE" ]]; then
    MODEL_PATH="$(cd "$(dirname "$MODEL_FILE")" && pwd)/$(basename "$MODEL_FILE")"
  elif [[ -f "${MODELS_DIR}/${MODEL_FILE}" ]]; then
    MODEL_PATH="${MODELS_DIR}/${MODEL_FILE}"
  else
    MODEL_PATH="${MODELS_DIR}/${MODEL_FILE}"
  fi
}

resolve_model_path

resolve_llama_server() {
  if [[ -n "${LLAMA_SERVER:-}" && -x "$LLAMA_SERVER" ]]; then
    export LD_LIBRARY_PATH="${BIN_DIR}:${LD_LIBRARY_PATH:-}"
    return 0
  fi
  if [[ -x "${BIN_DIR}/llama-server" ]]; then
    LLAMA_SERVER="${BIN_DIR}/llama-server"
    export LD_LIBRARY_PATH="${BIN_DIR}:${LD_LIBRARY_PATH:-}"
    return 0
  fi
  if command -v llama-server >/dev/null 2>&1; then
    LLAMA_SERVER="$(command -v llama-server)"
    return 0
  fi
  LLAMA_SERVER=""
  return 1
}

host_ram_gb() {
  "${REPO_ROOT}/.venv/bin/python" -c 'import psutil; print(round(psutil.virtual_memory().total/1024**3,1))' 2>/dev/null \
    || python3 -c 'import os; print(round(os.sysconf("SC_PAGE_SIZE")*os.sysconf("SC_PHYS_PAGES")/1024**3,1))' 2>/dev/null \
    || awk '/MemTotal/ {printf "%.1f", $2/1024/1024}' /proc/meminfo 2>/dev/null \
    || echo "?"
}

host_ram_avail_gb() {
  "${REPO_ROOT}/.venv/bin/python" -c 'import psutil; print(round(psutil.virtual_memory().available/1024**3,1))' 2>/dev/null \
    || awk '/MemAvailable/ {printf "%.1f", $2/1024/1024}' /proc/meminfo 2>/dev/null \
    || echo "?"
}

physical_cores() {
  "${REPO_ROOT}/.venv/bin/python" -c 'import psutil; print(psutil.cpu_count(logical=False) or "?")' 2>/dev/null \
    || awk '/^cpu cores/ {print $4; exit}' /proc/cpuinfo 2>/dev/null \
    || echo "?"
}

activate_client() {
  # shellcheck disable=SC1091
  [[ -f "${REPO_ROOT}/.venv/bin/activate" ]] && source "${REPO_ROOT}/.venv/bin/activate"
}

server_config_json() {
  export MODEL_PATH LLAMA_THREADS LLAMA_THREADS_BATCH LLAMA_PARALLEL LLAMA_CTX_SIZE
  export LLAMA_BATCH_SIZE LLAMA_N_GPU_LAYERS LLAMA_PORT SERVED_MODEL_NAME NPROC
  python3 -c '
import json, os
parallel = int(os.environ.get("LLAMA_PARALLEL", "8"))
ctx_per_slot = int(os.environ.get("LLAMA_CTX_SIZE", "4096"))
print(json.dumps({
  "engine": "llama.cpp",
  "model_path": os.environ.get("MODEL_PATH", ""),
  "served_model_name": os.environ.get("SERVED_MODEL_NAME", ""),
  "port": int(os.environ.get("LLAMA_PORT", "8010")),
  "threads": int(os.environ.get("LLAMA_THREADS", "0")),
  "threads_batch": int(os.environ.get("LLAMA_THREADS_BATCH", "0")),
  "parallel": parallel,
  "ctx_size_per_slot": ctx_per_slot,
  "ctx_size_total": ctx_per_slot * parallel,
  "batch_size": int(os.environ.get("LLAMA_BATCH_SIZE", "512")),
  "n_gpu_layers": int(os.environ.get("LLAMA_N_GPU_LAYERS", "0")),
  "logical_cores": int(os.environ.get("NPROC", "0")),
}))
'
}

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
    --backend cpu \
    --structured-mode "$STRUCTURED_MODE" \
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
# Setup / install llama-server
# ---------------------------------------------------------------------------
download_llama_server_release() {
  mkdir -p "$BIN_DIR"
  local arch
  arch="$(uname -m)"
  local asset=""
  case "$arch" in
    x86_64|amd64) asset="llama-b*-bin-ubuntu-x64.tar.gz" ;;
    aarch64|arm64) asset="llama-b*-bin-ubuntu-arm64.tar.gz" ;;
    *)
      echo "Unsupported arch $arch for prebuilt download. Build from source." >&2
      return 1
      ;;
  esac

  echo "Fetching latest llama.cpp release asset matching: $asset"
  local api_json tmp_tar extract_dir
  api_json="$(mktemp)"
  tmp_tar="$(mktemp --suffix=.tar.gz)"
  extract_dir="$(mktemp -d)"
  local api_ok=0
  for repo in "ggml-org/llama.cpp" "ggerganov/llama.cpp"; do
    if curl -fsSL "https://api.github.com/repos/${repo}/releases/latest" -o "$api_json"; then
      api_ok=1
      break
    fi
  done
  if [[ "$api_ok" -ne 1 ]]; then
    echo "Failed to query GitHub releases." >&2
    rm -f "$api_json" "$tmp_tar"
    rm -rf "$extract_dir"
    return 1
  fi

  local url
  url="$(python3 - "$api_json" "$arch" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
arch = sys.argv[2]
want = "ubuntu-x64" if arch in ("x86_64", "amd64") else "ubuntu-arm64"
cands = []
for a in data.get("assets") or []:
    name = a.get("name") or ""
    if want in name and name.endswith(".tar.gz") and "bin" in name:
        cands.append(a["browser_download_url"])
# prefer non-cuda / cpu-ish if multiple
cands.sort(key=lambda u: ("cuda" in u.lower(), u))
print(cands[0] if cands else "")
PY
)"
  if [[ -z "$url" ]]; then
    echo "No matching prebuilt tarball in latest release. See cpu/README.md to build from source." >&2
    rm -f "$api_json" "$tmp_tar"
    rm -rf "$extract_dir"
    return 1
  fi
  echo "Downloading: $url"
  curl -fL --progress-bar "$url" -o "$tmp_tar"
  tar -xzf "$tmp_tar" -C "$extract_dir"
  local found
  found="$(find "$extract_dir" -type f -name 'llama-server' | head -n1)"
  if [[ -z "$found" ]]; then
    echo "llama-server not found inside archive." >&2
    rm -f "$api_json" "$tmp_tar"
    rm -rf "$extract_dir"
    return 1
  fi
  local found_dir
  found_dir="$(dirname "$found")"
  # Clear previous install; copy binary + all shared libs (preserve soname symlinks).
  find "$BIN_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -d "$found" "${BIN_DIR}/llama-server"
  chmod +x "${BIN_DIR}/llama-server"
  # shellcheck disable=SC2086
  find "$found_dir" -maxdepth 1 \( -name 'lib*.so' -o -name 'lib*.so.*' \) -print0 \
    | xargs -0 -I{} cp -d {} "$BIN_DIR/"
  rm -f "$api_json" "$tmp_tar"
  rm -rf "$extract_dir"
  LLAMA_SERVER="${BIN_DIR}/llama-server"
  export LD_LIBRARY_PATH="${BIN_DIR}:${LD_LIBRARY_PATH:-}"
  echo "Installed: $LLAMA_SERVER"
  "$LLAMA_SERVER" --version 2>&1 | head -n5 || true
}

cmd_setup() {
  python3 -m venv "${REPO_ROOT}/.venv"
  activate_client
  pip install -U pip
  pip install -r "${REPO_ROOT}/requirements.txt"
  pip install -U huggingface_hub

  mkdir -p "$MODELS_DIR" "$BIN_DIR"

  if resolve_llama_server; then
    echo "llama-server found: $LLAMA_SERVER"
    "$LLAMA_SERVER" --version 2>&1 | head -n5 || true
  else
    echo "llama-server not found — downloading prebuilt binary..."
    download_llama_server_release
  fi

  echo ""
  echo "Client deps ready."
  cmd_show_env
}

cmd_download_model() {
  mkdir -p "$MODELS_DIR"
  resolve_model_path
  if [[ -f "$MODEL_PATH" ]]; then
    echo "Model already present: $MODEL_PATH"
    ls -lh "$MODEL_PATH"
    return 0
  fi
  if [[ -n "${HF_TOKEN:-}" ]]; then
    export HF_TOKEN
    export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
  fi
  echo "Downloading $HF_GGUF_FILE from $HF_GGUF_REPO -> $MODELS_DIR"
  activate_client
  # Prefer `hf` CLI (huggingface_hub); fall back to python helper.
  if command -v hf >/dev/null 2>&1; then
    hf download "$HF_GGUF_REPO" "$HF_GGUF_FILE" --local-dir "$MODELS_DIR"
  else
    "${REPO_ROOT}/.venv/bin/python" - <<PY
from huggingface_hub import hf_hub_download
path = hf_hub_download(
    repo_id="${HF_GGUF_REPO}",
    filename="${HF_GGUF_FILE}",
    local_dir="${MODELS_DIR}",
)
print("saved:", path)
PY
  fi
  # Normalize to MODEL_FILE name if HF filename differs
  if [[ -f "${MODELS_DIR}/${HF_GGUF_FILE}" && "${HF_GGUF_FILE}" != "${MODEL_FILE}" ]]; then
    ln -sfn "$HF_GGUF_FILE" "${MODELS_DIR}/${MODEL_FILE}"
  fi
  resolve_model_path
  if [[ ! -f "$MODEL_PATH" ]]; then
    # try case-insensitive match
    local hit
    hit="$(find "$MODELS_DIR" -maxdepth 1 -type f -iname '*q4_k_m*.gguf' | head -n1 || true)"
    if [[ -n "$hit" ]]; then
      ln -sfn "$(basename "$hit")" "${MODELS_DIR}/${MODEL_FILE}"
      resolve_model_path
    fi
  fi
  if [[ ! -f "$MODEL_PATH" ]]; then
    echo "Download finished but $MODEL_PATH missing. Check models/:" >&2
    ls -la "$MODELS_DIR" >&2
    exit 1
  fi
  ls -lh "$MODEL_PATH"
}

llama_common_args() {
  resolve_model_path
  if [[ ! -f "$MODEL_PATH" ]]; then
    echo "Model not found: $MODEL_PATH" >&2
    echo "Run: ./commands.sh download_model" >&2
    exit 1
  fi
  # llama.cpp splits --ctx-size across --parallel slots (unless unified KV).
  # LLAMA_CTX_SIZE is the desired per-slot context.
  local total_ctx=$((LLAMA_CTX_SIZE * LLAMA_PARALLEL))
  printf '%s\n' \
    --model "$MODEL_PATH" \
    --alias "$SERVED_MODEL_NAME" \
    --host "$LLAMA_HOST" \
    --port "$LLAMA_PORT" \
    --threads "$LLAMA_THREADS" \
    --threads-batch "$LLAMA_THREADS_BATCH" \
    --parallel "$LLAMA_PARALLEL" \
    --ctx-size "$total_ctx" \
    --batch-size "$LLAMA_BATCH_SIZE" \
    --n-gpu-layers "$LLAMA_N_GPU_LAYERS"
}

cmd_start_llama() {
  if ! resolve_llama_server; then
    echo "llama-server missing. Run: ./commands.sh setup" >&2
    exit 1
  fi
  if [[ -n "${HF_TOKEN:-}" ]]; then
    export HF_TOKEN
    export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
  fi
  echo "Starting llama-server (CPU):"
  echo "  model=$MODEL_PATH"
  echo "  threads=$LLAMA_THREADS threads_batch=$LLAMA_THREADS_BATCH parallel=$LLAMA_PARALLEL"
  echo "  ctx=$LLAMA_CTX_SIZE batch=$LLAMA_BATCH_SIZE ngl=$LLAMA_N_GPU_LAYERS port=$LLAMA_PORT"
  echo "  host_cores logical=$NPROC physical=$(physical_cores) ram_total=$(host_ram_gb)GB ram_avail=$(host_ram_avail_gb)GB"
  mapfile -t llama_args < <(llama_common_args)
  # Prefer binary dir for shared libs
  export LD_LIBRARY_PATH="${BIN_DIR}:${LD_LIBRARY_PATH:-}"
  exec "$LLAMA_SERVER" "${llama_args[@]}"
}

cmd_start_llama_bg() {
  if [[ -f "$LLAMA_PID_FILE" ]] && kill -0 "$(cat "$LLAMA_PID_FILE")" 2>/dev/null; then
    echo "llama-server already running (pid $(cat "$LLAMA_PID_FILE"))"
    return 0
  fi
  if ! resolve_llama_server; then
    echo "llama-server missing. Run: ./commands.sh setup" >&2
    exit 1
  fi
  if [[ -n "${HF_TOKEN:-}" ]]; then
    export HF_TOKEN
    export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
  fi
  echo "Starting llama-server in background -> $LLAMA_LOG"
  echo "  threads=$LLAMA_THREADS parallel=$LLAMA_PARALLEL cores=$NPROC"
  mapfile -t llama_args < <(llama_common_args)
  export LD_LIBRARY_PATH="${BIN_DIR}:${LD_LIBRARY_PATH:-}"
  nohup "$LLAMA_SERVER" "${llama_args[@]}" >"$LLAMA_LOG" 2>&1 &
  echo $! >"$LLAMA_PID_FILE"
  echo "pid $(cat "$LLAMA_PID_FILE")"
}

cmd_wait_llama() {
  local timeout="${1:-600}"
  local elapsed=0
  echo "Waiting for $BASE_URL/v1/models (timeout ${timeout}s)..."
  while (( elapsed < timeout )); do
    if curl -sf "$BASE_URL/v1/models" >/dev/null 2>&1; then
      echo "llama-server is ready."
      cmd_health
      cmd_show_env
      return 0
    fi
    if [[ -f "$LLAMA_PID_FILE" ]] && ! kill -0 "$(cat "$LLAMA_PID_FILE")" 2>/dev/null; then
      echo "llama-server process exited. Last log lines:" >&2
      tail -n 40 "$LLAMA_LOG" >&2 || true
      return 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "Timed out waiting for llama-server." >&2
  tail -n 40 "$LLAMA_LOG" >&2 || true
  return 1
}

cmd_stop_llama() {
  if [[ -f "$LLAMA_PID_FILE" ]]; then
    local pid
    pid="$(cat "$LLAMA_PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
      echo "Stopped llama-server (pid $pid)"
    fi
    rm -f "$LLAMA_PID_FILE"
  else
    echo "No pid file at $LLAMA_PID_FILE"
  fi
}

cmd_health() {
  curl -sS "$BASE_URL/v1/models" | python3 -m json.tool
}

cmd_show_env() {
  resolve_model_path
  resolve_llama_server || true
  cat <<EOF
backend=cpu (llama.cpp)
MODEL_FILE=$MODEL_FILE
MODEL_PATH=$MODEL_PATH
SERVED_MODEL_NAME=$SERVED_MODEL_NAME
BASE_URL=$BASE_URL
LLAMA_PORT=$LLAMA_PORT
LLAMA_THREADS=$LLAMA_THREADS
LLAMA_THREADS_BATCH=$LLAMA_THREADS_BATCH
LLAMA_PARALLEL=$LLAMA_PARALLEL
LLAMA_CTX_SIZE=$LLAMA_CTX_SIZE
LLAMA_CTX_TOTAL=$((LLAMA_CTX_SIZE * LLAMA_PARALLEL))
LLAMA_BATCH_SIZE=$LLAMA_BATCH_SIZE
LLAMA_N_GPU_LAYERS=$LLAMA_N_GPU_LAYERS
CONCURRENCY=$CONCURRENCY
TTFT_MS=$TTFT_MS MIN_TPS=$MIN_TPS
STOP_TTFT_MS=$STOP_TTFT_MS STOP_MIN_TPS=$STOP_MIN_TPS
SWEEP_START=$SWEEP_START SWEEP_MAX=$SWEEP_MAX SWEEP_STEP=$SWEEP_STEP
SUSTAINED_CONCURRENCY=$SUSTAINED_CONCURRENCY SUSTAINED_WAVES=$SUSTAINED_WAVES
STRUCTURED_MODE=$STRUCTURED_MODE
LLAMA_SERVER=${LLAMA_SERVER:-<not found>}
host_logical_cores=$NPROC
host_physical_cores=$(physical_cores)
ram_total_gb=$(host_ram_gb)
ram_available_gb=$(host_ram_avail_gb)
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
      \"response_format\": {
        \"type\": \"json_schema\",
        \"json_schema\": {
          \"name\": \"rephrase\",
          \"schema\": {
            \"type\": \"object\",
            \"properties\": {
              \"original\": {\"type\": \"string\"},
              \"rephrased\": {\"type\": \"string\"}
            },
            \"required\": [\"original\", \"rephrased\"]
          }
        }
      }
    }" | python3 -m json.tool
}

cmd_run_all() {
  cmd_setup
  cmd_download_model
  cmd_start_llama_bg
  cmd_wait_llama 600
  cmd_stress
}

usage() {
  cat <<EOF
Usage: ./commands.sh <command>

CPU (llama.cpp) stress tests — uses all cores by default.
Config: edit .env then restart server if model/server flags change.
  ./commands.sh show_env

Lifecycle:
  setup                 Client venv + install/locate llama-server
  download_model        Fetch GGUF into models/
  show_env              Print threads, parallel, cores, RAM, model
  start_llama           Launch llama-server in foreground
  start_llama_bg        Launch llama-server in background
  wait_llama [secs]     Wait until /v1/models responds
  stop_llama            Stop background server
  health                GET /v1/models
  smoke_plain           Single plain rephrase
  smoke_structured      Single JSON-schema rephrase
  run_all               setup + download + start_bg + wait + stress

Stress tests (same as GPU path):
  stress                Fixed concurrency
  stress_soak           Same concurrency, 5x requests
  stress_structured     Fixed concurrency + JSON schema
  stress_find_limit     Ramp concurrency until stop criteria
  stress_sustained      Many waves at SUSTAINED_CONCURRENCY

Typical limit hunt:
  ./commands.sh stop_llama
  ./commands.sh start_llama_bg
  ./commands.sh wait_llama
  ./commands.sh stress_find_limit
EOF
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    setup) cmd_setup ;;
    download_model) cmd_download_model ;;
    show_env) cmd_show_env ;;
    start_llama) cmd_start_llama ;;
    start_llama_bg) cmd_start_llama_bg ;;
    wait_llama) cmd_wait_llama "${2:-600}" ;;
    stop_llama) cmd_stop_llama ;;
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
