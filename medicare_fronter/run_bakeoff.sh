#!/usr/bin/env bash
# Medicare fronter model bake-off: correctness (+ light stress) across models.
# Logs everything under results/bakeoff_<timestamp>/
#
#   ./run_bakeoff.sh
#   MODELS="Qwen/Qwen2.5-3B-Instruct Qwen/Qwen2.5-7B-Instruct" ./run_bakeoff.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
GPU_DIR="${REPO_ROOT}/gpu"
GPU_ENV="${GPU_DIR}/.env"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${ROOT}/results/bakeoff_${STAMP}"
LOG="${OUT_DIR}/bakeoff.log"
SUMMARY_JSON="${OUT_DIR}/bakeoff_summary.json"
REPORT_MD="${OUT_DIR}/BAKEOFF_REPORT.md"

mkdir -p "$OUT_DIR"

# model_path|served_name|quantization(empty ok)|label
DEFAULT_MODELS=(
  "Qwen/Qwen2.5-3B-Instruct|Qwen/Qwen2.5-3B-Instruct||qwen2.5-3b"
  "Qwen/Qwen3-4B-Instruct-2507|Qwen/Qwen3-4B-Instruct-2507||qwen3-4b"
  "microsoft/Phi-4-mini-instruct|microsoft/Phi-4-mini-instruct||phi-4-mini"
  "google/gemma-4-E4B-it|google/gemma-4-E4B-it||gemma-4-e4b"
  "Qwen/Qwen2.5-7B-Instruct|Qwen/Qwen2.5-7B-Instruct||qwen2.5-7b"
)

log() {
  echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"
}

set_gpu_model() {
  local path="$1" served="$2" quant="${3:-}"
  python3 - "$GPU_ENV" "$path" "$served" "$quant" <<'PY'
import sys
from pathlib import Path
env_path, model_path, served, quant = sys.argv[1:5]
text = Path(env_path).read_text()
lines = []
seen_mp = seen_sm = seen_q = False
for line in text.splitlines():
    if line.startswith("MODEL_PATH="):
        lines.append(f"MODEL_PATH={model_path}")
        seen_mp = True
    elif line.startswith("SERVED_MODEL_NAME="):
        lines.append(f"SERVED_MODEL_NAME={served}")
        seen_sm = True
    elif line.startswith("VLLM_QUANTIZATION="):
        lines.append(f"VLLM_QUANTIZATION={quant}")
        seen_q = True
    else:
        lines.append(line)
if not seen_mp:
    lines.append(f"MODEL_PATH={model_path}")
if not seen_sm:
    lines.append(f"SERVED_MODEL_NAME={served}")
if not seen_q:
    lines.append(f"VLLM_QUANTIZATION={quant}")
Path(env_path).write_text("\n".join(lines) + "\n")
print(f"Updated {env_path}: MODEL_PATH={model_path} QUANT={quant or '<none>'}")
PY
}

run_one() {
  local path="$1" served="$2" quant="$3" label="$4"
  local model_dir="${OUT_DIR}/${label}"
  mkdir -p "$model_dir"
  local model_log="${model_dir}/run.log"

  log "======== START ${label} (${path}) ========"
  set_gpu_model "$path" "$served" "$quant"

  (
    cd "$GPU_DIR"
    ./commands.sh stop_vllm || true
    sleep 2
    ./commands.sh start_vllm_bg
    ./commands.sh wait_vllm 900
  ) >>"$model_log" 2>&1 || {
    log "FAIL start_vllm for ${label} — see ${model_log}"
    echo "{\"label\":\"${label}\",\"model_path\":\"${path}\",\"status\":\"vllm_start_failed\",\"log\":\"${model_log}\"}" \
      >"${model_dir}/status.json"
    return 1
  }

  local served_id
  served_id="$(curl -sf http://127.0.0.1:8000/v1/models \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null || echo "$served")"
  log "Served model id: ${served_id}"

  (
    cd "$ROOT"
    export PROMPT_STYLE=auto
    export MODEL="$served_id"
    ./commands.sh correctness
    CONCURRENCY=10 REQUESTS=20 ./commands.sh stress_turns
    CONCURRENCY=5 SESSIONS=5 ./commands.sh stress_sessions
  ) >>"$model_log" 2>&1 || {
    log "WARN: some harness commands failed for ${label}"
  }

  # Copy latest matching result JSONs into model dir
  python3 - "$ROOT/results" "$model_dir" "$served_id" "$label" "$path" <<'PY'
import json, re, sys
from pathlib import Path
from datetime import datetime, timezone
results_root, model_dir, served_id, label, model_path = sys.argv[1:6]
results_root = Path(results_root)
model_dir = Path(model_dir)
slug = re.sub(r"[^a-z0-9]+", "-", served_id.lower()).strip("-")[:80]

def newest(pattern):
    files = sorted(results_root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None

copied = {}
for kind, pat in [
    ("correctness", f"fronter_correctness_{slug}.json"),
    ("stress_turns", f"fronter_stress_turns_{slug}_*.json"),
    ("stress_sessions", f"fronter_stress_sessions_{slug}_*.json"),
]:
    # also try looser slug match
    f = newest(pat)
    if f is None:
        f = newest(f"fronter_{kind.replace('_','*')}_*.json")
    if f and f.exists():
        dest = model_dir / f.name
        dest.write_bytes(f.read_bytes())
        # also copy md if present
        md = f.with_suffix(".md")
        if md.exists():
            (model_dir / md.name).write_bytes(md.read_bytes())
        copied[kind] = str(dest)

status = {
    "label": label,
    "model_path": model_path,
    "served_id": served_id,
    "status": "ok" if "correctness" in copied else "missing_correctness",
    "copied": copied,
    "finished_at": datetime.now(timezone.utc).isoformat(),
}
if "correctness" in copied:
    data = json.loads(Path(copied["correctness"]).read_text())
    m = data.get("metrics") or {}
    status["correctness"] = {
        "passed_scenarios": data.get("passed_scenarios"),
        "total_scenarios": data.get("total_scenarios"),
        "ok_rate": m.get("ok_rate"),
        "error_rate": m.get("error_rate"),
        "schema_ok_rate": m.get("schema_ok_rate"),
        "ttft_p50_ms": m.get("ttft_p50_ms"),
        "ttft_p95_ms": m.get("ttft_p95_ms"),
        "total_p50_ms": m.get("total_p50_ms"),
        "total_p95_ms": m.get("total_p95_ms"),
        "tps_avg": m.get("tps_avg"),
        "prompt_style": data.get("prompt_style"),
        "scenario_results": [
            {"id": s.get("id"), "passed": s.get("passed")}
            for s in (data.get("scenarios") or [])
        ],
        "failed_detail": [],
    }
    for s in data.get("scenarios") or []:
        if s.get("passed"):
            continue
        fails = []
        for t in s.get("turns") or []:
            if t.get("ok"):
                continue
            p = t.get("parsed") or {}
            fails.append({
                "turn": t.get("turn_index"),
                "action": p.get("action"),
                "next": p.get("next"),
                "expect_errors": t.get("expect_errors"),
                "state_machine_errors": t.get("state_machine_errors"),
                "message": (p.get("message") or "")[:160],
            })
        status["correctness"]["failed_detail"].append({"id": s.get("id"), "fails": fails})

for kind in ("stress_turns", "stress_sessions"):
    if kind not in copied:
        continue
    data = json.loads(Path(copied[kind]).read_text())
    m = data.get("metrics") or {}
    status[kind] = {
        "ok_rate": m.get("ok_rate"),
        "error_rate": m.get("error_rate"),
        "ttft_p50_ms": m.get("ttft_p50_ms"),
        "ttft_p95_ms": m.get("ttft_p95_ms"),
        "total_p50_ms": m.get("total_p50_ms"),
        "total_p95_ms": m.get("total_p95_ms"),
        "tps_avg": m.get("tps_avg"),
        "tps_min": m.get("tps_min"),
        "concurrency": data.get("concurrency"),
        "session_pass_rate": data.get("session_pass_rate"),
    }

Path(model_dir / "status.json").write_text(json.dumps(status, indent=2))
print(json.dumps({"label": label, "status": status.get("status"),
                  "passed": (status.get("correctness") or {}).get("passed_scenarios"),
                  "total": (status.get("correctness") or {}).get("total_scenarios")}))
PY
  log "======== DONE ${label} ========"
}

# Resolve model list
MODELS_TO_RUN=()
if [[ -n "${MODELS:-}" ]]; then
  # space-separated HF ids; served name = path; no quant
  for m in $MODELS; do
    label="$(echo "$m" | tr '/A-Z' '-a-z' | tr -cd 'a-z0-9._-' | cut -c1-40)"
    MODELS_TO_RUN+=("${m}|${m}||${label}")
  done
else
  MODELS_TO_RUN=("${DEFAULT_MODELS[@]}")
fi

log "Bake-off output: ${OUT_DIR}"
log "Models: ${#MODELS_TO_RUN[@]}"

ok_count=0
fail_count=0
for entry in "${MODELS_TO_RUN[@]}"; do
  IFS='|' read -r path served quant label <<<"$entry"
  if run_one "$path" "$served" "$quant" "$label"; then
    ok_count=$((ok_count + 1))
  else
    fail_count=$((fail_count + 1))
  fi
done

# Aggregate summary + markdown report
python3 - "$OUT_DIR" "$SUMMARY_JSON" "$REPORT_MD" "$STAMP" <<'PY'
import json, sys
from pathlib import Path
from datetime import datetime, timezone

out_dir, summary_path, report_path, stamp = sys.argv[1:5]
out_dir = Path(out_dir)
rows = []
for status_file in sorted(out_dir.glob("*/status.json")):
    rows.append(json.loads(status_file.read_text()))

summary = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "stamp": stamp,
    "models": rows,
    "policy_notes": [
        "Dual DNC+abuse flags allowed on end_abuse/dnc",
        "Ask-again OK on no_parts / no_time (continue accepted)",
        "Early transfer before eligible remains a HARD fail",
        "Prompt style auto: compact for small models, full for 7B-class",
    ],
}
Path(summary_path).write_text(json.dumps(summary, indent=2))

lines = [
    "# Medicare Fronter Model Bake-off Report",
    "",
    f"**Stamp:** `{stamp}`  ",
    f"**Generated:** {summary['generated_at']}  ",
    f"**Output dir:** `{out_dir}`  ",
    "",
    "## Scoring policy (this run)",
    "",
]
for n in summary["policy_notes"]:
    lines.append(f"- {n}")

lines += [
    "",
    "## Correctness leaderboard",
    "",
    "| Rank | Model | Pass | Turn OK | Err | Schema | Prompt | TTFT p50/p95 | Gen p50 | TPS |",
    "|-----:|-------|-----:|--------:|----:|-------:|--------|-------------:|--------:|----:|",
]

ranked = sorted(
    rows,
    key=lambda r: (
        -((r.get("correctness") or {}).get("passed_scenarios") or -1),
        -((r.get("correctness") or {}).get("ok_rate") or -1),
    ),
)
for i, r in enumerate(ranked, 1):
    c = r.get("correctness") or {}
    if not c:
        lines.append(
            f"| {i} | `{r.get('label')}` | — | — | — | — | — | — | — | — |"
        )
        continue
    lines.append(
        f"| {i} | `{r.get('served_id') or r.get('label')}` | "
        f"{c.get('passed_scenarios')}/{c.get('total_scenarios')} | "
        f"{c.get('ok_rate')} | {c.get('error_rate')} | {c.get('schema_ok_rate')} | "
        f"{c.get('prompt_style')} | {c.get('ttft_p50_ms')}/{c.get('ttft_p95_ms')} | "
        f"{c.get('total_p50_ms')} | {c.get('tps_avg')} |"
    )

lines += ["", "## Per-model scenario matrix", ""]
# collect scenario ids
ids = []
for r in ranked:
    c = r.get("correctness") or {}
    for s in c.get("scenario_results") or []:
        if s["id"] not in ids:
            ids.append(s["id"])
if ids:
    header = "| Scenario | " + " | ".join(f"`{r.get('label')}`" for r in ranked) + " |"
    sep = "|----------|" + "|".join(["------"] * len(ranked)) + "|"
    lines += [header, sep]
    for sid in ids:
        cells = []
        for r in ranked:
            c = r.get("correctness") or {}
            m = {s["id"]: s["passed"] for s in (c.get("scenario_results") or [])}
            if sid not in m:
                cells.append("—")
            else:
                cells.append("PASS" if m[sid] else "FAIL")
        lines.append(f"| `{sid}` | " + " | ".join(cells) + " |")

lines += ["", "## Stress (10c turns / 5c sessions)", ""]
lines += [
    "| Model | Turns OK | Turns TTFT p95 | Turns TPS | Sess pass | Sess TTFT p95 |",
    "|-------|---------:|---------------:|----------:|----------:|--------------:|",
]
for r in ranked:
    st = r.get("stress_turns") or {}
    ss = r.get("stress_sessions") or {}
    lines.append(
        f"| `{r.get('label')}` | {st.get('ok_rate')} | {st.get('ttft_p95_ms')} | "
        f"{st.get('tps_avg')} | {ss.get('session_pass_rate')} | {ss.get('ttft_p95_ms')} |"
    )

lines += ["", "## Failure details (hard fails only)", ""]
for r in ranked:
    c = r.get("correctness") or {}
    fails = c.get("failed_detail") or []
    if not fails:
        continue
    lines.append(f"### `{r.get('label')}`")
    lines.append("")
    for fd in fails:
        lines.append(f"- **{fd['id']}**")
        for f in fd.get("fails") or []:
            lines.append(
                f"  - turn {f.get('turn')}: action=`{f.get('action')}` next=`{f.get('next')}` "
                f"— {f.get('expect_errors') or f.get('state_machine_errors')}"
            )
            if f.get("message"):
                lines.append(f"    - msg: {f['message']}")
    lines.append("")

lines += [
    "",
    "## Artifacts",
    "",
    f"- Summary JSON: `{summary_path}`",
    f"- Per-model folders under `{out_dir}/`",
    f"- Full console log: `{out_dir / 'bakeoff.log'}`",
    "",
]
Path(report_path).write_text("\n".join(lines))
print(f"Wrote {summary_path}")
print(f"Wrote {report_path}")
PY

# Also copy report to stable path
cp -f "$REPORT_MD" "${ROOT}/results/BAKEOFF_REPORT_LATEST.md"
cp -f "$SUMMARY_JSON" "${ROOT}/results/bakeoff_summary_latest.json"

log "Bake-off complete. ok=${ok_count} fail_start=${fail_count}"
log "Report: ${REPORT_MD}"
log "Latest copy: ${ROOT}/results/BAKEOFF_REPORT_LATEST.md"

# leave last model running (7B if that was last)
exit 0
