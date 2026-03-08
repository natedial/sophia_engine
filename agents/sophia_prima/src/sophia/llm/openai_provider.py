"""OpenAI-compatible implementation of the ModelProvider protocol."""

from __future__ import annotations

import json
import re
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
        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"OpenAI API timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"OpenAI API transport error: {exc}") from exc
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
        token_param = _max_tokens_param_for_model(model)
        payload: dict[str, Any] = {
            "model": model,
            token_param: max_tokens,
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
        content = _coerce_content_to_text(message_raw.get("content"))

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

        # Groq gpt-oss models can emit tool calls inline in message content
        # instead of OpenAI's `tool_calls` array. Parse those tags as a fallback.
        if not tool_calls:
            content, tool_calls = _extract_inline_tool_calls(content)

        stop_reason = _STOP_REASON_MAP.get(choice.get("finish_reason"), StopReason.END_TURN)
        if tool_calls:
            stop_reason = StopReason.TOOL_USE
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


_INLINE_TOOL_CALL_RE = re.compile(
    r"<\|tool_call_begin\|>(?P<name>.*?)"
    r"<\|tool_call_argument_begin\|>(?P<args>.*?)"
    r"<\|tool_call_end\|>",
    flags=re.DOTALL,
)


def _max_tokens_param_for_model(model: str) -> str:
    """Map model families to OpenAI token-budget parameter names."""
    if model.strip().lower().startswith("gpt-5"):
        return "max_completion_tokens"
    return "max_tokens"


def _coerce_content_to_text(content: Any) -> str:
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
    if content is None:
        return ""
    return str(content)


def _extract_inline_tool_calls(content: str) -> tuple[str, list[ToolCall]]:
    if "<|tool_call_begin|>" not in content:
        return content, []

    matches = list(_INLINE_TOOL_CALL_RE.finditer(content))
    if not matches:
        return content, []

    tool_calls: list[ToolCall] = []
    cleaned = content
    for i, match in enumerate(matches):
        raw_name = match.group("name").strip()
        args_raw = match.group("args").strip()
        tool_id = f"tool_call_{i + 1}"

        if ":" in raw_name:
            name_head, name_tail = raw_name.rsplit(":", 1)
            if name_tail.strip().isdigit():
                raw_name = name_head.strip()
                tool_id = f"tool_call_{name_tail.strip()}"

        if raw_name.startswith("functions."):
            raw_name = raw_name[len("functions.") :]

        if not raw_name:
            continue

        tool_calls.append(
            ToolCall(
                id=tool_id,
                name=raw_name,
                input=_parse_tool_arguments(args_raw),
            )
        )

        cleaned = cleaned.replace(match.group(0), "")

    cleaned = (
        cleaned.replace("<|tool_calls_section_begin|>", "")
        .replace("<|tool_calls_section_end|>", "")
        .strip()
    )
    return cleaned, tool_calls
