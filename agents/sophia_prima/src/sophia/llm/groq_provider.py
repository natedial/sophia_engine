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
            lowered = str(exc).lower()
            if "timeout" in lowered or "timed out" in lowered:
                raise RuntimeError(f"Groq API timeout: {exc}") from exc
            if status in {401, 413, 429}:
                fallback = await asyncio.to_thread(
                    self._fallback_client.post,
                    "/chat/completions",
                    json=payload,
                )
                if fallback.status_code < 400:
                    return OpenAIProvider._parse_response(fallback.json())

                # If token windows are exceeded, retry with progressively smaller payloads.
                if fallback.status_code in {413, 429}:
                    slim_payload = _build_slim_payload(payload)
                    slim = await asyncio.to_thread(
                        self._fallback_client.post,
                        "/chat/completions",
                        json=slim_payload,
                    )
                    if slim.status_code < 400:
                        return OpenAIProvider._parse_response(slim.json())

                    emergency_payload = _build_emergency_payload(payload)
                    emergency = await asyncio.to_thread(
                        self._fallback_client.post,
                        "/chat/completions",
                        json=emergency_payload,
                    )
                    if emergency.status_code < 400:
                        return OpenAIProvider._parse_response(emergency.json())

                    raise RuntimeError(
                        f"Groq API error HTTP {emergency.status_code}: {emergency.text}"
                    ) from exc

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


def _build_slim_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a reduced payload for constrained Groq plans.

    Drops tool schemas and reduces max_tokens to improve odds of fitting
    model/org token windows.
    """
    slim = dict(payload)
    slim.pop("tools", None)
    slim.pop("tool_choice", None)
    max_tokens = int(slim.get("max_tokens", 512) or 512)
    slim["max_tokens"] = min(max_tokens, 512)
    return slim


def _build_emergency_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal payload likely to fit strict TPM limits."""
    messages = payload.get("messages") or []
    system_text = ""
    latest_user_text = ""
    latest_any_text = ""

    for msg in messages:
        role = str(msg.get("role") or "")
        content = _as_text(msg.get("content"))
        if role == "system" and content and not system_text:
            system_text = content
        if role == "user" and content:
            latest_user_text = content
        if content:
            latest_any_text = content

    prompt_text = latest_user_text or latest_any_text or "Please respond concisely."
    emergency_messages: list[dict[str, str]] = []
    if system_text:
        emergency_messages.append({"role": "system", "content": _truncate(system_text, 1200)})
    emergency_messages.append({"role": "user", "content": _truncate(prompt_text, 2000)})

    emergency = dict(payload)
    emergency["messages"] = emergency_messages
    emergency.pop("tools", None)
    emergency.pop("tool_choice", None)
    max_tokens = int(emergency.get("max_tokens", 256) or 256)
    emergency["max_tokens"] = min(max_tokens, 256)
    return emergency


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""
