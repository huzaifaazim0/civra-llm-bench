"""insanely-fast-whisper STT adapter (in-process or subprocess via IFW_PYTHON)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_lock = asyncio.Lock()
_pipe = None
_pipe_device: str | None = None


def _ensure_path() -> None:
    root = os.environ.get("IFW_ROOT", "/root/.cvr/stt/insanely-fast-whisper")
    if root not in sys.path:
        sys.path.insert(0, root)


def _can_import_pipeline() -> bool:
    try:
        import transformers  # noqa: F401

        return True
    except Exception:
        return False


def _load_pipeline(device: str):
    global _pipe, _pipe_device
    if _pipe is not None and _pipe_device == device:
        return _pipe
    _ensure_path()
    import torch
    from transformers import pipeline

    model_id = os.environ.get("IFW_MODEL", "openai/whisper-large-v3")
    torch_dtype = torch.float16 if device.startswith("cuda") else torch.float32
    kwargs: dict[str, Any] = {
        "model": model_id,
        "torch_dtype": torch_dtype,
        "device": device if device != "cuda" else 0,
    }
    flash = os.environ.get("IFW_FLASH", "0") == "1"
    if flash and str(device).startswith("cuda"):
        kwargs["model_kwargs"] = {"attn_implementation": "flash_attention_2"}
    _pipe = pipeline("automatic-speech-recognition", **kwargs)
    _pipe_device = device
    return _pipe


_WORKER_SRC = r"""
import json, os, sys, time
from pathlib import Path
device = os.environ.get("IFW_DEVICE", "cuda")
model_id = os.environ.get("IFW_MODEL", "openai/whisper-large-v3")
wav = Path(sys.argv[1])
import torch
from transformers import pipeline
torch_dtype = torch.float16 if str(device).startswith("cuda") else torch.float32
dev = 0 if device == "cuda" else device
pipe = pipeline("automatic-speech-recognition", model=model_id, torch_dtype=torch_dtype, device=dev)
t0 = time.perf_counter()
out = pipe(str(wav), return_timestamps=False)
ms = (time.perf_counter() - t0) * 1000.0
text = (out.get("text") if isinstance(out, dict) else str(out) or "").strip()
print(json.dumps({"text": text, "stt_ms": ms, "device": device}))
"""


class IFWSTT:
    name = "ifw"
    streaming = False

    def __init__(self, device: str | None = None):
        self.device = device or os.environ.get("IFW_DEVICE", "cuda")
        self.device_hint = self.device
        self._use_subproc = not _can_import_pipeline()
        self._ifw_python = os.environ.get(
            "IFW_PYTHON",
            os.path.join(os.environ.get("IFW_ROOT", "/root/.cvr/stt/insanely-fast-whisper"), ".venv/bin/python"),
        )

    async def health(self) -> bool:
        try:
            if self._use_subproc:
                return Path(self._ifw_python).exists()
            await asyncio.to_thread(_load_pipeline, self.device)
            return True
        except Exception:
            return False

    def _transcribe_sync(self, wav_path: Path) -> tuple[str, float, dict[str, Any]]:
        pipe = _load_pipeline(self.device)
        t0 = time.perf_counter()
        out = pipe(str(wav_path), return_timestamps=False)
        ms = (time.perf_counter() - t0) * 1000.0
        if isinstance(out, dict):
            text = (out.get("text") or "").strip()
        else:
            text = str(out).strip()
        return text, ms, {"mode": "batch", "device": self.device, "stt_streaming": False}

    def _transcribe_subproc(self, wav_path: Path) -> tuple[str, float, dict[str, Any]]:
        import subprocess

        env = os.environ.copy()
        env["IFW_DEVICE"] = self.device
        t0 = time.perf_counter()
        proc = subprocess.run(
            [self._ifw_python, "-c", _WORKER_SRC, str(wav_path)],
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-2000:] or proc.stdout[-2000:] or f"ifw exit {proc.returncode}")
        data = json.loads(proc.stdout.strip().splitlines()[-1])
        wall = (time.perf_counter() - t0) * 1000.0
        return (
            data["text"],
            float(data.get("stt_ms", wall)),
            {"mode": "subprocess", "device": self.device, "stt_streaming": False, "wall_ms": wall},
        )

    async def transcribe(self, wav_path: Path) -> tuple[str, float, dict[str, Any]]:
        async with _lock:
            if self._use_subproc:
                return await asyncio.to_thread(self._transcribe_subproc, Path(wav_path))
            return await asyncio.to_thread(self._transcribe_sync, Path(wav_path))

    async def transcribe_ws(self, wav_path: Path) -> tuple[str, float, float | None, dict[str, Any]]:
        text, ms, meta = await self.transcribe(wav_path)
        return text, ms, None, meta
