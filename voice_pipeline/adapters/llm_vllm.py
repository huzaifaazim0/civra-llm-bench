"""vLLM streaming chat client."""

from __future__ import annotations

import json
import os
import time
from typing import Any, AsyncIterator

import httpx


class VLLMLLM:
    name = "vllm"

    def __init__(
        self,
        base: str | None = None,
        model: str | None = None,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        disable_thinking: bool | None = None,
    ):
        self.base = (base or os.environ.get("VLLM_BASE", "http://127.0.0.1:8000")).rstrip("/")
        self.model = model  # if None, query /v1/models
        self.system = system or os.environ.get(
            "LLM_SYSTEM",
            "You are a concise helpful phone agent. Reply in 1-2 short spoken sentences.",
        )
        self.max_tokens = max_tokens or int(os.environ.get("LLM_MAX_TOKENS", "64"))
        self.temperature = (
            temperature if temperature is not None else float(os.environ.get("LLM_TEMPERATURE", "0.3"))
        )
        self.disable_thinking = (
            disable_thinking
            if disable_thinking is not None
            else os.environ.get("DISABLE_THINKING", "1") == "1"
        )
        self._resolved_model: str | None = None

    async def resolve_model(self) -> str:
        if self.model:
            self._resolved_model = self.model
            return self.model
        if self._resolved_model:
            return self._resolved_model
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(f"{self.base}/v1/models")
            r.raise_for_status()
            data = r.json()
            mid = data["data"][0]["id"]
        self._resolved_model = mid
        return mid

    async def health(self) -> bool:
        try:
            await self.resolve_model()
            return True
        except Exception:
            return False

    async def stream_chat(self, user_text: str) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield (delta_text, meta) tokens. meta may include ttft_ms on first token."""
        model = await self.resolve_model()
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
        }
        if self.disable_thinking:
            body["chat_template_kwargs"] = {"enable_thinking": False}

        t0 = time.perf_counter()
        first = True
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", f"{self.base}/v1/chat/completions", json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content") or ""
                    if not content:
                        continue
                    meta: dict[str, Any] = {}
                    if first:
                        meta["ttft_ms"] = (time.perf_counter() - t0) * 1000.0
                        first = False
                    yield content, meta
        # end
