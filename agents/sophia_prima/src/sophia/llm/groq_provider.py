"""Groq SDK implementation of the ModelProvider protocol."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, AsyncIterator

import httpx

from sophia.llm.base import StreamComplete, StreamEvent
from sophia.llm.openai_provider import OpenAIProvider
from sophia.llm.types import CompletionResponse, Message, ToolSchema


class GroqProvider:
    """Groq provider backed by the official AsyncGroq SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.groq.com",
        timeout: float = 60.0,
    ) -> None:
        try:
            from groq import AsyncGroq
        except ImportError as exc:  # pragma: no cover - depends on runtime deps
            raise RuntimeError(
                "Groq provider requested but 'groq' package is not installed. "
                "Install project dependencies or add groq to your environment."
            ) from exc

        sdk_base_url = _normalize_groq_base_url(base_url)
        self._client: Any = AsyncGroq(
            api_key=api_key,
            base_url=sdk_base_url,
            timeout=timeout,
        )
        self._fallback_client = httpx.Client(
            base_url=f"{sdk_base_url}/openai/v1",
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResponse:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": OpenAIProvider._messages_to_openai(system=system, messages=messages),
        }
        if tools:
            payload["tools"] = [OpenAIProvider._tool_to_openai(t) for t in tools]
            payload["tool_choice"] = "auto"

        try:
            response = await self._client.chat.completions.create(**payload)
        except Exception as exc:
            status = getattr(exc, "status_code", "unknown")
            if status == 401:
                fallback = await asyncio.to_thread(
                    self._fallback_client.post,
                    "/chat/completions",
                    json=payload,
                )
                if fallback.status_code < 400:
                    return OpenAIProvider._parse_response(fallback.json())
                raise RuntimeError(
                    f"Groq API error HTTP {fallback.status_code}: {fallback.text}"
                ) from exc
            raise RuntimeError(f"Groq API error HTTP {status}: {exc}") from exc

        raw = response.model_dump()
        return OpenAIProvider._parse_response(raw)

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        completion = await self.complete(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        yield StreamComplete(response=completion)

    async def close(self) -> None:
        close_result = self._client.close()
        if inspect.isawaitable(close_result):
            await close_result
        await asyncio.to_thread(self._fallback_client.close)


def _normalize_groq_base_url(raw: str) -> str:
    """Normalize Groq base URL for SDK usage.

    Groq's Python SDK already appends `/openai/v1` internally. If callers pass
    an OpenAI-style URL ending with `/openai/v1`, strip it to avoid duplicated
    request paths like `/openai/v1/openai/v1/...`.
    """
    base = (raw or "https://api.groq.com").strip().rstrip("/")
    suffix = "/openai/v1"
    if base.endswith(suffix):
        base = base[: -len(suffix)] or "https://api.groq.com"
    return base
