"""Shared types for voice pipeline adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class StageTimings:
    stt_ms: float | None = None
    stt_partial_ms: float | None = None
    llm_ttft_ms: float | None = None
    llm_total_ms: float | None = None
    llm_tokens: int = 0
    tts_ttfa_ms: float | None = None
    tts_total_ms: float | None = None
    e2e_ttfa_ms: float | None = None
    e2e_total_ms: float | None = None
    transcript: str = ""
    reply_text: str = ""
    audio_bytes: int = 0
    error: str | None = None
    ok: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def split_sentences(buf: str) -> tuple[list[str], str]:
    """Return complete sentences and leftover buffer."""
    out: list[str] = []
    start = 0
    for i, ch in enumerate(buf):
        if ch in ".!?":
            # keep going if next looks like abbreviation digit
            if i + 1 < len(buf) and buf[i + 1].isalnum():
                continue
            piece = buf[start : i + 1].strip()
            if piece:
                out.append(piece)
            start = i + 1
    return out, buf[start:]
