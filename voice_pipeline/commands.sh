#!/usr/bin/env bash
# Voice pipeline stress harness
#
#   ./commands.sh setup
#   ./commands.sh start_servers --llm 3b
#   ./commands.sh run --stt parakeet --llm 3b --tts kokoro --smoke
#   ./commands.sh run --stt parakeet --llm 3b --tts kokoro --find-limit
#   ./commands.sh run_matrix --find-limit
#   ./commands.sh write_results_md

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GPU_DIR="$(cd "$ROOT/../gpu" && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
cd "$ROOT"

load_env() {
  local env_file="${ENV_FILE:-$ROOT/.env}"
  if [[ -f "$env_file" ]]; then
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
  fi
}

load_env

PARAKEET_REALTIME_ROOT="${PARAKEET_REALTIME_ROOT:-/root/.cvr/parakeet_realtime}"
KOKORO_REALTIME_ROOT="${KOKORO_REALTIME_ROOT:-/root/.cvr/kokoro-tts-realtime}"
GPU_COMMANDS="${GPU_COMMANDS:-$GPU_DIR/commands.sh}"
CLIENT_PY="${CLIENT_PY:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$CLIENT_PY" ]]; then
  CLIENT_PY="python3"
fi

llm_model_env() {
  local key="$1"
  case "$key" in
    moe)
      export MODEL_PATH="QuixiAI/Qwen3-30B-A3B-AWQ"
      export SERVED_MODEL_NAME="QuixiAI/Qwen3-30B-A3B-AWQ"
      export VLLM_QUANTIZATION="awq_marlin"
      export DTYPE="float16"
      # MoE AWQ needs nearly full card for weights + any KV; 0.78 leaves negative KV.
      export GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION_MOE:-0.95}"
      export MAX_MODEL_LEN="${MAX_MODEL_LEN_MOE:-4096}"
      export MAX_NUM_SEQS="${MAX_NUM_SEQS_MOE:-64}"
      export DISABLE_THINKING=1
      ;;
    3b)
      export MODEL_PATH="Qwen/Qwen2.5-3B-Instruct"
      export SERVED_MODEL_NAME="Qwen/Qwen2.5-3B-Instruct"
      export VLLM_QUANTIZATION=""
      export DTYPE="bfloat16"
      export GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION_3B:-0.45}"
      export MAX_MODEL_LEN="${MAX_MODEL_LEN_3B:-4096}"
      export MAX_NUM_SEQS="${MAX_NUM_SEQS_3B:-128}"
      ;;
    7b)
      export MODEL_PATH="Qwen/Qwen2.5-7B-Instruct"
      export SERVED_MODEL_NAME="Qwen/Qwen2.5-7B-Instruct"
      export VLLM_QUANTIZATION="${VLLM_QUANTIZATION_7B:-fp8}"
      export DTYPE="${DTYPE_7B:-bfloat16}"
      export GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION_7B:-0.55}"
      export MAX_MODEL_LEN="${MAX_MODEL_LEN_7B:-4096}"
      export MAX_NUM_SEQS="${MAX_NUM_SEQS_7B:-96}"
      ;;
    *)
      echo "unknown llm key: $key (moe|3b|7b)" >&2
      exit 1
      ;;
  esac
}

cmd_setup() {
  if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
    python3 -m venv "$REPO_ROOT/.venv"
  fi
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.venv/bin/activate"
  pip install -U pip
  pip install -r "$REPO_ROOT/requirements.txt"
  pip install "websockets>=12" "numpy>=1.24"
  cp -n "$ROOT/.env.example" "$ROOT/.env" 2>/dev/null || true
  echo "Client ready: $(which python)"
}

wait_http() {
  local url="$1"
  local name="$2"
  local tries="${3:-90}"
  local i
  for ((i=1; i<=tries; i++)); do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo "$name ready"
      return 0
    fi
    sleep 2
  done
  echo "$name not ready: $url" >&2
  return 1
}

cmd_start_parakeet() {
  local model="${PARAKEET_MODEL:-}"
  if curl -sf "http://127.0.0.1:37283/v1/health" >/dev/null 2>&1; then
    echo "parakeet already healthy"
    return 0
  fi
  if [[ -n "$model" ]]; then
    mkdir -p "$ROOT/tmp"
    local tmpenv="$ROOT/tmp/parakeet.env"
    if [[ -f "$PARAKEET_REALTIME_ROOT/.env" ]]; then
      grep -v '^MODEL=' "$PARAKEET_REALTIME_ROOT/.env" >"$tmpenv" || true
    fi
    echo "MODEL=$model" >>"$tmpenv"
    echo "Starting parakeet with MODEL=$model"
    ENV_FILE="$tmpenv" make -C "$PARAKEET_REALTIME_ROOT" start-bg
  else
    make -C "$PARAKEET_REALTIME_ROOT" start-bg
  fi
  wait_http "http://127.0.0.1:37283/v1/health" "parakeet" 180
}

cmd_stop_parakeet() {
  make -C "$PARAKEET_REALTIME_ROOT" stop || true
}

cmd_start_kokoro() {
  local device="${KOKORO_DEVICE:-}"
  if curl -sf "http://127.0.0.1:32432/v1/health" >/dev/null 2>&1; then
    echo "kokoro already healthy"
    return 0
  fi
  if [[ -n "$device" ]]; then
    mkdir -p "$ROOT/tmp"
    local tmpenv="$ROOT/tmp/kokoro.env"
    if [[ -f "$KOKORO_REALTIME_ROOT/.env" ]]; then
      grep -v '^DEVICE=' "$KOKORO_REALTIME_ROOT/.env" >"$tmpenv" || true
    fi
    echo "DEVICE=$device" >>"$tmpenv"
    echo "Starting kokoro with DEVICE=$device"
    ENV_FILE="$tmpenv" make -C "$KOKORO_REALTIME_ROOT" start-bg
  else
    make -C "$KOKORO_REALTIME_ROOT" start-bg
  fi
  wait_http "http://127.0.0.1:32432/v1/health" "kokoro" 180
}

cmd_stop_kokoro() {
  make -C "$KOKORO_REALTIME_ROOT" stop || true
}

cmd_ensure_llm() {
  local key="${1:?llm key}"
  llm_model_env "$key"
  # Push model settings into gpu/.env process env for commands.sh
  export MODEL_PATH SERVED_MODEL_NAME VLLM_QUANTIZATION DTYPE
  export GPU_MEMORY_UTILIZATION MAX_MODEL_LEN MAX_NUM_SEQS
  # Detect if already serving desired model
  local current=""
  current="$(curl -sf http://127.0.0.1:8000/v1/models 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["data"][0]["id"] if d.get("data") else "")' 2>/dev/null || true)"
  if [[ "$current" == "$MODEL_PATH" || "$current" == "$SERVED_MODEL_NAME" ]]; then
    echo "vLLM already serving $current"
    return 0
  fi
  echo "Restarting vLLM for $MODEL_PATH ..."
  "$GPU_COMMANDS" stop_vllm || true
  sleep 2
  # Write temporary overrides via env when invoking gpu commands
  MODEL_PATH="$MODEL_PATH" \
  SERVED_MODEL_NAME="$SERVED_MODEL_NAME" \
  VLLM_QUANTIZATION="$VLLM_QUANTIZATION" \
  DTYPE="$DTYPE" \
  GPU_MEMORY_UTILIZATION="$GPU_MEMORY_UTILIZATION" \
  MAX_MODEL_LEN="$MAX_MODEL_LEN" \
  MAX_NUM_SEQS="$MAX_NUM_SEQS" \
    "$GPU_COMMANDS" start_vllm_bg
  MODEL_PATH="$MODEL_PATH" \
  SERVED_MODEL_NAME="$SERVED_MODEL_NAME" \
    "$GPU_COMMANDS" wait_vllm
}

cmd_start_servers() {
  local llm="3b"
  local stt="parakeet"
  local tts="kokoro"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --llm) llm="$2"; shift 2 ;;
      --stt) stt="$2"; shift 2 ;;
      --tts) tts="$2"; shift 2 ;;
      *) echo "unknown: $1"; exit 1 ;;
    esac
  done

  # MoE: stop GPU STT/TTS, load MoE at full util, then start Parakeet/Kokoro on CPU.
  if [[ "$llm" == "moe" ]]; then
    cmd_stop_parakeet
    cmd_stop_kokoro
    sleep 2
  fi

  cmd_ensure_llm "$llm"

  if [[ "$stt" == "parakeet" ]]; then
    if [[ "$llm" == "moe" ]]; then
      PARAKEET_MODEL=v2-fp16-cpu cmd_start_parakeet || echo "WARN: parakeet cpu failed" >&2
    else
      unset PARAKEET_MODEL || true
      cmd_start_parakeet || echo "WARN: parakeet failed to start (VRAM?)" >&2
    fi
  else
    cmd_stop_parakeet
  fi
  if [[ "$tts" == "kokoro" ]]; then
    if [[ "$llm" == "moe" ]]; then
      KOKORO_DEVICE=cpu cmd_start_kokoro || echo "WARN: kokoro cpu failed" >&2
    else
      unset KOKORO_DEVICE || true
      cmd_start_kokoro || echo "WARN: kokoro failed to start (VRAM?)" >&2
    fi
  elif [[ "$llm" == "moe" ]]; then
    cmd_stop_kokoro
  fi
}

cmd_stop_servers() {
  cmd_stop_parakeet
  cmd_stop_kokoro
  "$GPU_COMMANDS" stop_vllm || true
}

cmd_run() {
  local stt="" llm="" tts="" find_limit=0 smoke=0 extra=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --stt) stt="$2"; shift 2 ;;
      --llm) llm="$2"; shift 2 ;;
      --tts) tts="$2"; shift 2 ;;
      --find-limit) find_limit=1; shift ;;
      --smoke) smoke=1; shift ;;
      *) extra+=("$1"); shift ;;
    esac
  done
  [[ -n "$stt" && -n "$llm" && -n "$tts" ]] || {
    echo "usage: run --stt ... --llm ... --tts ... [--find-limit|--smoke]" >&2
    exit 1
  }

  cmd_start_servers --llm "$llm" --stt "$stt" --tts "$tts"

  local args=(--stt "$stt" --llm "$llm" --tts "$tts")
  if [[ "$find_limit" == 1 ]]; then
    args+=(--find-limit)
  elif [[ "$smoke" == 1 ]]; then
    args+=(--smoke)
  fi
  args+=("${extra[@]}")

  export IFW_ROOT="${IFW_ROOT:-/root/.cvr/stt/insanely-fast-whisper}"
  export MELO_ROOT="${MELO_ROOT:-/root/.cvr/tts/melotts}"
  export NEUTTS_ROOT="${NEUTTS_ROOT:-/root/.cvr/tts/neutts}"

  if [[ "$tts" == "neutts" && "$llm" == "moe" ]]; then
    export CUDA_VISIBLE_DEVICES=""
    export NEUTTS_BACKBONE_DEVICE=cpu
  fi

  # Prefer an interpreter that can import in-process stages. When both STT and TTS
  # need different venvs, prefer TTS venv and run IFW via IFW_PYTHON subprocess.
  local py="$CLIENT_PY"
  if [[ "$tts" == "melo" && -x "$MELO_ROOT/.venv/bin/python" ]]; then
    py="$MELO_ROOT/.venv/bin/python"
  elif [[ "$tts" == "neutts" && -x "$NEUTTS_ROOT/.venv/bin/python" ]]; then
    py="$NEUTTS_ROOT/.venv/bin/python"
  elif [[ "$stt" == "ifw" && -x "$IFW_ROOT/.venv/bin/python" ]]; then
    py="$IFW_ROOT/.venv/bin/python"
  fi
  export IFW_PYTHON="${IFW_PYTHON:-$IFW_ROOT/.venv/bin/python}"

  echo "Using python: $py"
  "$py" "$ROOT/pipeline_stress.py" "${args[@]}"
}

cmd_run_matrix() {
  local find_limit=1
  local extra=()
  local force=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --find-limit) find_limit=1; shift ;;
      --smoke) find_limit=0; shift ;;
      --force) force=1; shift ;;
      *) extra+=("$1"); shift ;;
    esac
  done

  local results_dir="${RESULTS_DIR:-$ROOT/results}"
  local stts=(parakeet ifw)
  local llms=(3b 7b moe)
  local ttss=(kokoro melo neutts)
  local stt llm tts out
  for llm in "${llms[@]}"; do
    for stt in "${stts[@]}"; do
      for tts in "${ttss[@]}"; do
        out="$results_dir/${stt}__${llm}__${tts}.json"
        if [[ "$force" != 1 && -f "$out" ]]; then
          if python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('ok') else 1)" "$out" 2>/dev/null; then
            echo "======== SKIP $stt / $llm / $tts (exists) ========"
            continue
          fi
        fi
        echo "======== MATRIX $stt / $llm / $tts ========"
        # NeuTTS is slow — keep sweep modest so the matrix finishes.
        local sweep_extra=()
        if [[ "$tts" == "neutts" ]]; then
          sweep_extra=(--sweep-max "${NEUTTS_SWEEP_MAX:-4}")
        fi
        if [[ "$find_limit" == 1 ]]; then
          cmd_run --stt "$stt" --llm "$llm" --tts "$tts" --find-limit "${sweep_extra[@]}" "${extra[@]}" || true
        else
          cmd_run --stt "$stt" --llm "$llm" --tts "$tts" --smoke "${extra[@]}" || true
        fi
      done
    done
  done
  cmd_write_results_md
}

cmd_write_results_md() {
  "$CLIENT_PY" "$ROOT/pipeline_stress.py" --write-results-md
}

usage() {
  cat <<EOF
Voice pipeline stress

  setup                 Install client deps
  start_servers --llm 3b [--stt parakeet] [--tts kokoro]
  stop_servers
  ensure_llm moe|3b|7b
  run --stt parakeet --llm 3b --tts kokoro [--find-limit|--smoke]
  run_matrix [--find-limit|--smoke]
  write_results_md

Example:
  ./commands.sh run --stt parakeet --llm 3b --tts kokoro --find-limit
EOF
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    setup) cmd_setup ;;
    start_servers) cmd_start_servers "$@" ;;
    stop_servers) cmd_stop_servers ;;
    ensure_llm) cmd_ensure_llm "$@" ;;
    start_parakeet) cmd_start_parakeet ;;
    stop_parakeet) cmd_stop_parakeet ;;
    start_kokoro) cmd_start_kokoro ;;
    stop_kokoro) cmd_stop_kokoro ;;
    run) cmd_run "$@" ;;
    run_matrix) cmd_run_matrix "$@" ;;
    write_results_md) cmd_write_results_md ;;
    ""|-h|--help|help) usage ;;
    *) echo "unknown command: $cmd"; usage; exit 1 ;;
  esac
}

main "$@"
