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
    RESEARCH_PLAN_CREATED = "research_plan_created"
    SKILL_ACTIVATED = "skill_activated"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_UPDATE = "tool_execution_update"
    TOOL_EXECUTION_END = "tool_execution_end"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    SUBAGENT_ERROR = "subagent_error"


@dataclass
class AgentEvent:
    """A single event from the agent's execution."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def _inject_run_context(
    payload: dict[str, Any],
    *,
    run_id: str | None,
    parent_run_id: str | None,
    task_id: str | None,
) -> dict[str, Any]:
    if run_id is not None:
        payload["run_id"] = run_id
    if parent_run_id is not None:
        payload["parent_run_id"] = parent_run_id
    if task_id is not None:
        payload["task_id"] = task_id
    return payload


def agent_start(
    session_id: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.AGENT_START,
        data=_inject_run_context(
            {"session_id": session_id},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def agent_end(
    session_id: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.AGENT_END,
        data=_inject_run_context(
            {"session_id": session_id},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def turn_start(
    turn: int,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.TURN_START,
        data=_inject_run_context(
            {"turn": turn},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def turn_end(
    turn: int,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.TURN_END,
        data=_inject_run_context(
            {"turn": turn},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def message_start(
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.MESSAGE_START,
        data=_inject_run_context(
            {},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def message_delta(
    text: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.MESSAGE_DELTA,
        data=_inject_run_context(
            {"text": text},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def message_end(
    message: Message,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.MESSAGE_END,
        data=_inject_run_context(
            {"message": message},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def research_plan_created(
    playbook_id: str,
    summary: str,
    indicator_families: tuple[str, ...] = (),
    indicator_queries: tuple[dict[str, object], ...] = (),
    capability_checks: tuple[dict[str, object], ...] = (),
    acquisition_decisions: tuple[dict[str, object], ...] = (),
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.RESEARCH_PLAN_CREATED,
        data=_inject_run_context(
            {
                "playbook_id": playbook_id,
                "summary": summary,
                "indicator_families": indicator_families,
                "indicator_queries": indicator_queries,
                "capability_checks": capability_checks,
                "acquisition_decisions": acquisition_decisions,
            },
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def skill_activated(
    name: str,
    reason: str,
    score: float,
    path: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.SKILL_ACTIVATED,
        data=_inject_run_context(
            {
                "name": name,
                "reason": reason,
                "score": score,
                "path": path,
            },
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def tool_execution_start(
    tool_call: ToolCall,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.TOOL_EXECUTION_START,
        data=_inject_run_context(
            {"tool_call": tool_call},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def tool_execution_update(
    tool_call: ToolCall,
    text: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.TOOL_EXECUTION_UPDATE,
        data=_inject_run_context(
            {"tool_call": tool_call, "text": text},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def tool_execution_end(
    tool_call: ToolCall,
    result: str,
    is_error: bool = False,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.TOOL_EXECUTION_END,
        data=_inject_run_context(
            {"tool_call": tool_call, "result": result, "is_error": is_error},
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def subagent_start(
    name: str,
    task: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.SUBAGENT_START,
        data=_inject_run_context(
            {
                "name": name,
                "task": task,
            },
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def subagent_end(
    name: str,
    summary: str,
    *,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.SUBAGENT_END,
        data=_inject_run_context(
            {
                "name": name,
                "summary": summary,
            },
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )


def subagent_error(
    name: str,
    error: str,
    *,
    timed_out: bool = False,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    task_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        type=EventType.SUBAGENT_ERROR,
        data=_inject_run_context(
            {
                "name": name,
                "error": error,
                "timed_out": timed_out,
            },
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        ),
    )
