"""Generic LLM types - provider-agnostic message and tool definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    """Message role."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class StopReason(str, Enum):
    """Why the model stopped generating."""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResultMessage:
    """Result of a tool execution, to be sent back to the model."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """A single conversation message (any role).

    Holds text content, tool calls (assistant), or tool results (user).
    The optional _raw field stores the original provider response for debugging.
    """

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResultMessage] = field(default_factory=list)
    _raw: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class TokenUsage:
    """Token consumption for a single completion."""

    input_tokens: int
    output_tokens: int


@dataclass
class CompletionResponse:
    """Full response from a model completion call."""

    message: Message
    stop_reason: StopReason
    usage: TokenUsage


@dataclass(frozen=True)
class ToolSchema:
    """Provider-agnostic tool definition for the model."""

    name: str
    description: str
    input_schema: dict[str, Any]
