"""Typed agent events emitted by the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sophia.llm.types import Message, ToolCall


class EventType(str, Enum):
    """All event types emitted during an agent run."""

    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    MESSAGE_START = "message_start"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_END = "message_end"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"
    TOOL_EXECUTION_END = "tool_execution_end"


@dataclass
class AgentEvent:
    """A single event from the agent's execution."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def agent_start(session_id: str) -> AgentEvent:
    return AgentEvent(type=EventType.AGENT_START, data={"session_id": session_id})


def agent_end(session_id: str) -> AgentEvent:
    return AgentEvent(type=EventType.AGENT_END, data={"session_id": session_id})


def turn_start(turn: int) -> AgentEvent:
    return AgentEvent(type=EventType.TURN_START, data={"turn": turn})


def turn_end(turn: int) -> AgentEvent:
    return AgentEvent(type=EventType.TURN_END, data={"turn": turn})


def message_start() -> AgentEvent:
    return AgentEvent(type=EventType.MESSAGE_START)


def message_delta(text: str) -> AgentEvent:
    return AgentEvent(type=EventType.MESSAGE_DELTA, data={"text": text})


def message_end(message: Message) -> AgentEvent:
    return AgentEvent(type=EventType.MESSAGE_END, data={"message": message})


def tool_execution_start(tool_call: ToolCall) -> AgentEvent:
    return AgentEvent(
        type=EventType.TOOL_EXECUTION_START,
        data={"tool_call": tool_call},
    )


def tool_execution_update(tool_call: ToolCall, text: str) -> AgentEvent:
    return AgentEvent(
        type=EventType.TOOL_EXECUTION_UPDATE,
        data={"tool_call": tool_call, "text": text},
    )


def tool_execution_end(tool_call: ToolCall, result: str, is_error: bool = False) -> AgentEvent:
    return AgentEvent(
        type=EventType.TOOL_EXECUTION_END,
        data={"tool_call": tool_call, "result": result, "is_error": is_error},
    )
