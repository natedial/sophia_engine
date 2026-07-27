"""ModelProvider protocol and stream event types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

from sophia.llm.types import CompletionResponse, Message, ToolSchema


# ---------------------------------------------------------------------------
# Stream events
# ---------------------------------------------------------------------------


@dataclass
class StreamEvent:
    """Base class for streaming events from a provider."""


@dataclass
class ContentDelta(StreamEvent):
    """Incremental text content from the model."""

    text: str


@dataclass
class ToolCallDelta(StreamEvent):
    """Incremental tool call data (id assigned on first delta)."""

    tool_call_id: str
    name: str
    input_json_delta: str


@dataclass
class StreamComplete(StreamEvent):
    """Final event carrying the full CompletionResponse."""

    response: CompletionResponse


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ModelProvider(Protocol):
    """Structural interface for LLM providers.

    Implementations do NOT need to inherit from this class — they just need
    to expose the same method signatures (duck typing via Protocol).
    """

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResponse: ...

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]: ...

    async def close(self) -> None: ...
