"""Kokoro TTS adapter — WS streaming (one utterance per call for TTFA)."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any, AsyncIterator

import httpx

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None  # type: ignore


class KokoroTTS:
    name = "kokoro"
    streaming = True
    device_hint = "cuda"  # server-side

    def __init__(
        self,
        base: str | None = None,
        ws_url: str | None = None,
        voice: str | None = None,
    ):
        self.base = (base or os.environ.get("KOKORO_BASE", "http://127.0.0.1:32432")).rstrip("/")
        self.ws_url = ws_url or os.environ.get("KOKORO_WS") or self.base.replace("http", "ws") + "/v1/ws/tts"
        self.voice = voice or os.environ.get("KOKORO_VOICE", "af_heart")

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{self.base}/v1/health")
                return r.status_code == 200
        except Exception:
            return False

    async def synthesize_stream(self, text: str) -> AsyncIterator[tuple[bytes, dict[str, Any]]]:
        """Yield (audio_bytes, meta). First yield marks TTFA."""
        text = (text or "").strip()
        if not text:
            return
        if websockets is None:
            async for item in self._http_synth(text):
                yield item
            return

        t0 = time.perf_counter()
        first = True
        async with websockets.connect(self.ws_url, max_size=32 * 1024 * 1024) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "start",
                        "model": "kokoro",
                        "text": text,
                        "voice_id": self.voice,
                        "output_format": "wav",
                        "sample_rate_hz": 24000,
                    }
                )
            )
            await ws.send(json.dumps({"type": "end"}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=120.0))
                mtype = msg.get("type")
                if mtype == "error":
                    raise RuntimeError(msg.get("message") or msg.get("detail") or str(msg))
                b64 = msg.get("audio_base64")
                if b64:
                    raw = base64.b64decode(b64)
                    meta: dict[str, Any] = {"type": mtype}
                    if first:
                        meta["ttfa_ms"] = (time.perf_counter() - t0) * 1000.0
                        first = False
                    yield raw, meta
                if mtype in ("final", "error"):
                    break

    async def _http_synth(self, text: str) -> AsyncIterator[tuple[bytes, dict[str, Any]]]:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(
                f"{self.base}/v1/tts",
                json={
                    "text": text,
                    "voice_id": self.voice,
                    "output_format": "wav",
                    "model": "kokoro",
                },
            )
            r.raise_for_status()
            body = r.content
        yield body, {"ttfa_ms": (time.perf_counter() - t0) * 1000.0, "mode": "http"}
