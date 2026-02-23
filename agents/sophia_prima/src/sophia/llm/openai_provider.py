"""OpenAI-compatible implementation of the ModelProvider protocol."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from sophia.llm.base import StreamComplete, StreamEvent
from sophia.llm.types import (
    CompletionResponse,
    Message,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolSchema,
)

# Map OpenAI finish reasons to our generic enum
_STOP_REASON_MAP: dict[str, StopReason] = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.STOP_SEQUENCE,
}


class OpenAIProvider:
    """HTTPX-based OpenAI Chat Completions provider."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
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
        payload = self._build_request(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        response = await self._client.post("/chat/completions", json=payload)
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenAI API error HTTP {response.status_code}: {response.text}"
            )

        raw = response.json()
        return self._parse_response(raw)

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Fallback streaming implementation using a full completion call.

        This keeps provider behavior compatible with the existing agent loop
        even when incremental SSE parsing is not configured.
        """
        completion = await self.complete(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        yield StreamComplete(response=completion)

    async def close(self) -> None:
        await self._client.aclose()

    def _build_request(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": self._messages_to_openai(system=system, messages=messages),
        }
        if tools:
            payload["tools"] = [self._tool_to_openai(t) for t in tools]
            payload["tool_choice"] = "auto"
        return payload

    @staticmethod
    def _messages_to_openai(*, system: str, messages: list[Message]) -> list[dict[str, Any]]:
        wire: list[dict[str, Any]] = [{"role": "system", "content": system}]

        for msg in messages:
            # Tool results are represented as role=tool messages.
            if msg.tool_results:
                for tr in msg.tool_results:
                    wire.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            "content": tr.content,
                        }
                    )
                continue

            if msg.role == Role.ASSISTANT and msg.tool_calls:
                wire.append(
                    {
                        "role": "assistant",
                        "content": msg.content if msg.content else None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.input),
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
                continue

            wire.append(
                {
                    "role": msg.role.value,
                    "content": msg.content,
                }
            )

        return wire

    @staticmethod
    def _tool_to_openai(schema: ToolSchema) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": schema.name,
                "description": schema.description,
                "parameters": schema.input_schema,
            },
        }

    @staticmethod
    def _parse_response(raw: dict[str, Any]) -> CompletionResponse:
        choices = raw.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI API returned no choices")
        choice = choices[0]

        message_raw = choice.get("message", {})
        content = message_raw.get("content") or ""

        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(message_raw.get("tool_calls") or []):
            function = tc.get("function") or {}
            name = str(function.get("name") or "")
            args_raw = function.get("arguments") or "{}"
            tool_calls.append(
                ToolCall(
                    id=str(tc.get("id") or f"tool_call_{i + 1}"),
                    name=name,
                    input=_parse_tool_arguments(args_raw),
                )
            )

        stop_reason = _STOP_REASON_MAP.get(choice.get("finish_reason"), StopReason.END_TURN)
        usage_raw = raw.get("usage") or {}
        usage = TokenUsage(
            input_tokens=int(usage_raw.get("prompt_tokens", 0)),
            output_tokens=int(usage_raw.get("completion_tokens", 0)),
        )

        message = Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
            _raw=raw,
        )
        return CompletionResponse(
            message=message,
            stop_reason=stop_reason,
            usage=usage,
        )


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Parse tool arguments payload from OpenAI response."""
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        return {}

    payload = arguments.strip()
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        # Preserve raw payload for debugging while keeping dict contract.
        return {"_raw_arguments": payload}

    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}
