"""Parakeet STT adapter — HTTP batch + optional WS streaming."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import wave
from pathlib import Path
from typing import Any

import httpx

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore


# NeMo Parakeet engine is not safe for concurrent in-flight transcribes
# (race: "Cannot unfreeze partially..."). Serialize client-side; LLM/TTS
# stages can still overlap across calls after STT returns.
_parakeet_lock = asyncio.Lock()


class ParakeetSTT:
    name = "parakeet"
    streaming = True
    device_hint = "cuda"  # server-side; typically GPU

    def __init__(self, base: str = "http://127.0.0.1:37283", ws_url: str | None = None):
        self.base = base.rstrip("/")
        self.ws_url = ws_url or self.base.replace("http", "ws") + "/v1/ws/stt"

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.base}/v1/health")
                return r.status_code == 200
        except Exception:
            return False

    async def transcribe(self, wav_path: Path) -> tuple[str, float, dict[str, Any]]:
        """HTTP POST /v1/stt — returns (text, stt_ms, meta). Prefer JSON body."""
        raw = Path(wav_path).read_bytes()
        async with _parakeet_lock:
            t0 = time.perf_counter()
            async with httpx.AsyncClient(timeout=120.0) as c:
                r = await c.post(
                    f"{self.base}/v1/stt",
                    json={
                        "audio_base64": base64.b64encode(raw).decode("ascii"),
                        "mime_type": "audio/wav",
                        "model": "parakeet",
                        "language": "en",
                        "enable_vad": True,
                    },
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"parakeet HTTP {r.status_code}: {r.text[:500]}")
                data = r.json()
            ms = (time.perf_counter() - t0) * 1000.0
        text = (data.get("text") or data.get("transcript") or "").strip()
        return text, ms, {"mode": "http_json", "stt_serialized": True, "raw_keys": list(data.keys())}

    async def transcribe_ws(
        self, wav_path: Path, chunk_ms: int = 100
    ) -> tuple[str, float, float | None, dict[str, Any]]:
        """WS streaming — returns (text, total_ms, first_partial_ms, meta)."""
        if websockets is None:
            text, ms, meta = await self.transcribe(wav_path)
            return text, ms, None, meta

        path = Path(wav_path)
        with wave.open(str(path), "rb") as wf:
            if wf.getsampwidth() != 2:
                # fall back to HTTP for non-PCM16
                text, ms, meta = await self.transcribe(path)
                return text, ms, None, meta
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            pcm = wf.readframes(wf.getnframes())

        if channels > 1:
            import numpy as np

            audio = np.frombuffer(pcm, dtype="<i2").reshape(-1, channels)
            pcm = audio.mean(axis=1).astype("<i2").tobytes()

        frame_bytes = max(int(sample_rate * chunk_ms / 1000) * 2, 2)
        first_partial_ms: float | None = None
        final_text = ""

        async with _parakeet_lock:
            t0 = time.perf_counter()
            async with websockets.connect(self.ws_url, max_size=32 * 1024 * 1024) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "start",
                            "model": "parakeet",
                            "language": "en",
                            "enable_vad": True,
                            "sample_rate_hz": sample_rate,
                            "mime_type": "audio/pcm",
                        }
                    )
                )
                offset = 0
                seq = 0
                while offset < len(pcm):
                    chunk = pcm[offset : offset + frame_bytes]
                    offset += frame_bytes
                    seq += 1
                    await ws.send(
                        json.dumps(
                            {
                                "type": "audio",
                                "audio_base64": base64.b64encode(chunk).decode("ascii"),
                                "sequence": seq,
                                "final": offset >= len(pcm),
                            }
                        )
                    )
                await ws.send(json.dumps({"type": "end"}))

                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=120.0))
                    mtype = msg.get("type")
                    if mtype in ("partial", "transcript") and first_partial_ms is None:
                        first_partial_ms = (time.perf_counter() - t0) * 1000.0
                    if mtype == "final":
                        final_text = (msg.get("text") or msg.get("transcript") or "").strip()
                        break
                    if mtype == "error":
                        raise RuntimeError(msg.get("message") or msg)
            total_ms = (time.perf_counter() - t0) * 1000.0

        if not final_text:
            final_text, total_ms, meta = await self.transcribe(path)
            return final_text, total_ms, first_partial_ms, {**meta, "ws_fallback": True}
        return final_text, total_ms, first_partial_ms, {"mode": "ws", "stt_serialized": True}
