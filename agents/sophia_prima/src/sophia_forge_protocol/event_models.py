"""Event contracts for coding runtime runs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


RunEventType = Literal[
    "run_queued",
    "run_started",
    "context_assembled",
    "backend_started",
    "backend_finished",
    "run_progress",
    "run_heartbeat",
    "retry_scheduled",
    "retry_started",
    "retry_finished",
    "checkpoint_created",
    "control_message_queued",
    "control_message_applied",
    "control_message_rejected",
    "session_bound",
    "session_resumed",
    "verification_started",
    "verification_finished",
    "artifact_created",
    "run_completed",
    "run_blocked",
    "run_failed",
    "run_cancelled",
]


class RunEvent(BaseModel):
    """Canonical event emitted during a coding run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    sequence: int
    event_type: RunEventType
    timestamp: str
    payload: dict[str, Any] = Field(default_factory=dict)
