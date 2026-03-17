"""Types for append-only lossless history used for debugging and reflection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class HistoryEventType(str, Enum):
    """Append-only event types captured for lossless session history."""

    TURN_INPUT = "turn_input"
    TURN_OUTPUT = "turn_output"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"


@dataclass(frozen=True)
class HistoryEventRecord:
    """One persisted history event."""

    session_id: str
    event_type: HistoryEventType
    payload: dict[str, Any]
    run_id: str | None = None
    parent_run_id: str | None = None
    task_id: str | None = None
    turn: int | None = None
    created_at: datetime = field(default_factory=utc_now)
