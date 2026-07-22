"""NeuTTS Air Q4 adapter — infer_stream via thread (simple, lock-serialized)."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator

_thread_lock = threading.Lock()
_tts = None
_ref_codes = None
_ref_text: str | None = None
_cfg_key: str | None = None


def _ensure_path() -> None:
    root = os.environ.get("NEUTTS_ROOT", "/root/.cvr/tts/neutts")
    if root not in sys.path:
        sys.path.insert(0, root)


def _load():
    global _tts, _ref_codes, _ref_text, _cfg_key
    backbone = os.environ.get("NEUTTS_BACKBONE", "neuphonic/neutts-air-q4-gguf")
    backbone_device = os.environ.get("NEUTTS_BACKBONE_DEVICE", "gpu")
    codec = os.environ.get("NEUTTS_CODEC", "neuphonic/neucodec-onnx-decoder")
    codec_device = os.environ.get("NEUTTS_CODEC_DEVICE", "cpu")
    key = f"{backbone}|{backbone_device}|{codec}|{codec_device}"
    if _tts is not None and _cfg_key == key:
        return _tts, _ref_codes, _ref_text

    _ensure_path()
    import torch
    from neutts import NeuTTS

    _tts = NeuTTS(
        backbone_repo=backbone,
        backbone_device=backbone_device,
        codec_repo=codec,
        codec_device=codec_device,
        enable_watermark=False,
    )
    ref_codes_path = Path(os.environ.get("NEUTTS_REF_CODES", "/root/.cvr/tts/neutts/samples/jo.pt"))
    ref_text_path = Path(os.environ.get("NEUTTS_REF_TEXT", "/root/.cvr/tts/neutts/samples/jo.txt"))
    _ref_codes = torch.load(ref_codes_path, map_location="cpu", weights_only=False)
    _ref_text = ref_text_path.read_text(encoding="utf-8").strip()
    _cfg_key = key
    return _tts, _ref_codes, _ref_text


class NeuTTSTTS:
    name = "neutts"
    streaming = True

    def __init__(self, backbone_device: str | None = None):
        if backbone_device:
            os.environ["NEUTTS_BACKBONE_DEVICE"] = backbone_device
        self.device_hint = os.environ.get("NEUTTS_BACKBONE_DEVICE", "gpu")

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(_load)
            return True
        except Exception:
            return False

    def _synth_all(self, text: str) -> tuple[list[bytes], float]:
        """Return (chunks, ttfa_ms). Collect stream under lock."""
        import numpy as np

        with _thread_lock:
            tts, ref_codes, ref_text = _load()
            t0 = time.perf_counter()
            chunks: list[bytes] = []
            ttfa: float | None = None
            for chunk in tts.infer_stream(text, ref_codes, ref_text):
                if ttfa is None:
                    ttfa = (time.perf_counter() - t0) * 1000.0
                chunks.append((np.asarray(chunk) * 32767.0).astype(np.int16).tobytes())
            return chunks, float(ttfa or 0.0)

    async def synthesize_stream(self, text: str) -> AsyncIterator[tuple[bytes, dict[str, Any]]]:
        text = (text or "").strip()
        if not text:
            return
        chunks, ttfa = await asyncio.to_thread(self._synth_all, text)
        first = True
        for audio in chunks:
            meta: dict[str, Any] = {"sample_rate": 24000}
            if first:
                meta["ttfa_ms"] = ttfa
                first = False
            yield audio, meta
