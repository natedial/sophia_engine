"""Anthropic implementation of the ModelProvider protocol."""

from __future__ import annotations

from typing import Any, AsyncIterator

import anthropic

from sophia.llm.base import ContentDelta, StreamComplete, StreamEvent, ToolCallDelta
from sophia.llm.types import (
    CompletionResponse,
    Message,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolSchema,
)

# Map Anthropic stop reasons to our generic enum
_STOP_REASON_MAP: dict[str, StopReason] = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
}


class AnthropicProvider:
    """AsyncAnthropic-based provider — all Anthropic SDK usage is isolated here."""

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # Public API (matches ModelProvider protocol)
    # ------------------------------------------------------------------

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResponse:
        kwargs = self._build_request(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        raw = await self._client.messages.create(**kwargs)
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
        kwargs = self._build_request(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        async with self._client.messages.stream(**kwargs) as stream:
            # Track tool call state for assembling ToolCallDelta events
            current_tool_id: str | None = None
            current_tool_name: str | None = None

            async for event in stream:
                converted = self._convert_stream_event(
                    event, current_tool_id, current_tool_name
                )
                if converted is not None:
                    # Update tracking state for tool_use blocks
                    if isinstance(converted, ToolCallDelta):
                        current_tool_id = converted.tool_call_id
                        current_tool_name = converted.name
                    yield converted

            # Emit the final complete event with the assembled response
            final_message = await stream.get_final_message()
            yield StreamComplete(response=self._parse_response(final_message))

    async def close(self) -> None:
        await self._client.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_request(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema] | None,
        max_tokens: int,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [self._message_to_anthropic(m) for m in messages],
        }
        if tools:
            kwargs["tools"] = [self._tool_to_anthropic(t) for t in tools]
        return kwargs

    @staticmethod
    def _message_to_anthropic(msg: Message) -> dict[str, Any]:
        """Convert a generic Message to Anthropic wire format."""
        # Tool results → user message with tool_result blocks
        if msg.tool_results:
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tr.tool_call_id,
                        "content": tr.content,
                        **({"is_error": True} if tr.is_error else {}),
                    }
                    for tr in msg.tool_results
                ],
            }

        # Assistant message with tool calls → content blocks
        if msg.role == Role.ASSISTANT and msg.tool_calls:
            blocks: list[dict[str, Any]] = []
            if msg.content:
                blocks.append({"type": "text", "text": msg.content})
            for tc in msg.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            return {"role": "assistant", "content": blocks}

        # Simple text message
        return {"role": msg.role.value, "content": msg.content}

    @staticmethod
    def _tool_to_anthropic(schema: ToolSchema) -> dict[str, Any]:
        return {
            "name": schema.name,
            "description": schema.description,
            "input_schema": schema.input_schema,
        }

    @staticmethod
    def _parse_response(raw: anthropic.types.Message) -> CompletionResponse:
        """Convert an Anthropic Message to a generic CompletionResponse."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in raw.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, input=block.input)
                )

        stop = _STOP_REASON_MAP.get(raw.stop_reason, StopReason.END_TURN)
        usage = TokenUsage(
            input_tokens=raw.usage.input_tokens,
            output_tokens=raw.usage.output_tokens,
        )

        message = Message(
            role=Role.ASSISTANT,
            content="".join(text_parts),
            tool_calls=tool_calls,
            _raw=raw,
        )

        return CompletionResponse(message=message, stop_reason=stop, usage=usage)

    @staticmethod
    def _convert_stream_event(
        event: Any,
        current_tool_id: str | None,
        current_tool_name: str | None,
    ) -> StreamEvent | None:
        """Map an Anthropic stream event to a generic StreamEvent (or None to skip)."""
        event_type = getattr(event, "type", None)

        if event_type == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                return ToolCallDelta(
                    tool_call_id=block.id,
                    name=block.name,
                    input_json_delta="",
                )
            return None

        if event_type == "content_block_delta":
            delta = event.delta
            if delta.type == "text_delta":
                return ContentDelta(text=delta.text)
            if delta.type == "input_json_delta":
                return ToolCallDelta(
                    tool_call_id=current_tool_id or "",
                    name=current_tool_name or "",
                    input_json_delta=delta.partial_json,
                )
            return None

        # All other events (message_start, message_delta, etc.) are ignored —
        # the final message is captured via stream.get_final_message().
        return None
