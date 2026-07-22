"""MeloTTS adapter — in-process, sentence-chunked WAV (pseudo-stream)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncIterator

_lock = asyncio.Lock()
_model = None
_model_device: str | None = None
_spk2id: dict | None = None


def _ensure_path() -> None:
    root = os.environ.get("MELO_ROOT", "/root/.cvr/tts/melotts")
    if root not in sys.path:
        sys.path.insert(0, root)


def _load(device: str):
    global _model, _model_device, _spk2id
    if _model is not None and _model_device == device:
        return _model, _spk2id
    _ensure_path()
    from melo.api import TTS

    language = os.environ.get("MELO_LANGUAGE", "EN")
    _model = TTS(language=language, device=device)
    _spk2id = _model.hps.data.spk2id
    _model_device = device
    return _model, _spk2id


class MeloTTS:
    name = "melo"
    streaming = False  # sentence-level pseudo-stream

    def __init__(self, device: str | None = None):
        self.device = device or os.environ.get("MELO_DEVICE", "cuda")
        self.device_hint = self.device
        self.speaker = os.environ.get("MELO_SPEAKER", "EN-US")

    async def health(self) -> bool:
        try:
            async with _lock:
                await asyncio.to_thread(_load, self.device)
            return True
        except Exception:
            return False

    def _synth_sync(self, text: str) -> tuple[bytes, float]:
        model, spk2id = _load(self.device)
        speaker = self.speaker
        if speaker not in spk2id:
            for k in spk2id:
                if str(k).upper().replace("_", "-") == speaker.upper().replace("_", "-"):
                    speaker = k
                    break
            else:
                speaker = next(iter(spk2id))
        t0 = time.perf_counter()
        fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            model.tts_to_file(text, spk2id[speaker], out_path, speed=1.0)
            data = Path(out_path).read_bytes()
        finally:
            with contextlib.suppress(OSError):
                os.unlink(out_path)
        ms = (time.perf_counter() - t0) * 1000.0
        return data, ms

    async def synthesize_stream(self, text: str) -> AsyncIterator[tuple[bytes, dict[str, Any]]]:
        text = (text or "").strip()
        if not text:
            return
        async with _lock:
            data, ms = await asyncio.to_thread(self._synth_sync, text)
        yield data, {"ttfa_ms": ms, "mode": "sentence_wav", "device": self.device, "tts_streaming": False}
