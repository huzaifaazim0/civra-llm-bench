"""JSON and Markdown report writers for medicare closer harness."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = int(round((len(ordered) - 1) * p))
    return round(ordered[k], 2)


def model_slug(model: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in model.lower()).strip("-")[:80]


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def summarize_turn_metrics(turns: list[dict[str, Any]]) -> dict[str, Any]:
    ttfts = [t["ttft_ms"] for t in turns if t.get("ttft_ms") is not None]
    totals = [t["total_ms"] for t in turns if t.get("total_ms") is not None]
    tps = [t["tokens_per_sec"] for t in turns if t.get("tokens_per_sec") is not None]
    ok = sum(1 for t in turns if t.get("ok"))
    schema_ok = sum(1 for t in turns if t.get("schema_ok"))
    n = len(turns)
    return {
        "turns": n,
        "ok_count": ok,
        "ok_rate": round(ok / n, 4) if n else None,
        "error_rate": round(1 - (ok / n), 4) if n else None,
        "schema_ok_count": schema_ok,
        "schema_ok_rate": round(schema_ok / n, 4) if n else None,
        "ttft_avg_ms": round(statistics.mean(ttfts), 2) if ttfts else None,
        "ttft_p50_ms": _pct(ttfts, 0.50),
        "ttft_p95_ms": _pct(ttfts, 0.95),
        "ttft_p99_ms": _pct(ttfts, 0.99),
        "ttft_max_ms": max(ttfts) if ttfts else None,
        "total_avg_ms": round(statistics.mean(totals), 2) if totals else None,
        "total_p50_ms": _pct(totals, 0.50),
        "total_p95_ms": _pct(totals, 0.95),
        "total_max_ms": max(totals) if totals else None,
        "tps_avg": round(statistics.mean(tps), 3) if tps else None,
        "tps_p50": _pct(tps, 0.50),
        "tps_min": min(tps) if tps else None,
    }


def write_correctness_markdown(path: Path, payload: dict[str, Any]) -> Path:
    model = payload.get("model", "unknown")
    metrics = payload.get("metrics") or {}
    scenarios = payload.get("scenarios") or []
    generated = payload.get("generated_at") or datetime.now(timezone.utc).isoformat()

    lines = [
        "# Medicare Closer Correctness Report",
        "",
        f"**Model:** `{model}`  ",
        f"**Generated:** {generated}  ",
        f"**Mode:** `{payload.get('mode', 'correctness')}`  ",
        f"**Scenarios:** {len(scenarios)}  ",
        f"**Turns:** {metrics.get('turns')}  ",
        f"**Pass rate (hard checks):** {metrics.get('ok_rate')}  ",
        f"**Schema OK rate:** {metrics.get('schema_ok_rate')}  ",
        f"**Error rate:** {metrics.get('error_rate')}  ",
        "",
        "## Latency",
        "",
        f"- TTFT avg / p50 / p95 / max (ms): "
        f"{metrics.get('ttft_avg_ms')} / {metrics.get('ttft_p50_ms')} / "
        f"{metrics.get('ttft_p95_ms')} / {metrics.get('ttft_max_ms')}",
        f"- Full generation avg / p50 / p95 / max (ms): "
        f"{metrics.get('total_avg_ms')} / {metrics.get('total_p50_ms')} / "
        f"{metrics.get('total_p95_ms')} / {metrics.get('total_max_ms')}",
        f"- TPS avg / p50 / min: "
        f"{metrics.get('tps_avg')} / {metrics.get('tps_p50')} / {metrics.get('tps_min')}",
        "",
        "## Per scenario",
        "",
        "| Scenario | Turns | Pass | Fail | Error rate |",
        "|----------|------:|-----:|-----:|-----------:|",
    ]
    for s in scenarios:
        turns = s.get("turns") or []
        n = len(turns)
        ok = sum(1 for t in turns if t.get("ok"))
        fail = n - ok
        er = round(fail / n, 4) if n else 0
        lines.append(f"| `{s.get('id')}` | {n} | {ok} | {fail} | {er} |")

    taxonomy = payload.get("error_taxonomy") or {}
    if taxonomy:
        lines += ["", "## Error taxonomy", ""]
        for key, count in sorted(taxonomy.items(), key=lambda x: -x[1]):
            lines.append(f"- **{key}:** {count}")

    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_stress_markdown(path: Path, payload: dict[str, Any]) -> Path:
    model = payload.get("model", "unknown")
    mode = payload.get("mode", "stress")
    metrics = payload.get("metrics") or {}
    generated = payload.get("generated_at") or datetime.now(timezone.utc).isoformat()
    lines = [
        f"# Medicare Closer {mode.replace('_', ' ').title()} Report",
        "",
        f"**Model:** `{model}`  ",
        f"**Generated:** {generated}  ",
        f"**Concurrency:** {payload.get('concurrency')}  ",
        f"**Mode:** `{mode}`  ",
        "",
        "## Results",
        "",
        f"- Turns: {metrics.get('turns')}",
        f"- OK rate: {metrics.get('ok_rate')}",
        f"- Error rate: {metrics.get('error_rate')}",
        f"- Schema OK rate: {metrics.get('schema_ok_rate')}",
        f"- TTFT p50 / p95 / max (ms): "
        f"{metrics.get('ttft_p50_ms')} / {metrics.get('ttft_p95_ms')} / {metrics.get('ttft_max_ms')}",
        f"- Full gen p50 / p95 / max (ms): "
        f"{metrics.get('total_p50_ms')} / {metrics.get('total_p95_ms')} / {metrics.get('total_max_ms')}",
        f"- TPS avg / min: {metrics.get('tps_avg')} / {metrics.get('tps_min')}",
        "",
    ]
    if payload.get("max_stable_concurrency") is not None:
        lines += [
            "## Find-limit",
            "",
            f"- **max_stable_concurrency:** {payload.get('max_stable_concurrency')}",
            f"- **stop_reason:** {payload.get('stop_reason')}",
            "",
        ]
    if payload.get("sweep"):
        lines += [
            "| Concurrency | TTFT p95 | TPS min | Error rate | Stop? |",
            "|------------:|---------:|--------:|-----------:|:------|",
        ]
        for row in payload["sweep"]:
            lines.append(
                f"| {row.get('concurrency')} | {row.get('ttft_p95_ms')} | "
                f"{row.get('tps_min')} | {row.get('error_rate')} | "
                f"{'yes' if row.get('stopped') else 'no'} |"
            )
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_freeform_transcript(
    path: Path,
    *,
    scenario_id: str,
    description: str,
    model: str,
    turns: list[dict[str, Any]],
) -> Path:
    lines = [
        f"# Freeform transcript — `{scenario_id}`",
        "",
        f"**Description:** {description}  ",
        f"**Model:** `{model}`  ",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ",
        "",
        "---",
        "",
    ]
    for t in turns:
        idx = t.get("turn_index", 0)
        user = t.get("user") or "(opening)"
        agent = t.get("agent_message") or t.get("text") or ""
        lines.append(f"### Turn {idx}")
        lines.append("")
        lines.append(f"**Caller:** {user}")
        lines.append("")
        lines.append(f"**Agent:** {agent}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
