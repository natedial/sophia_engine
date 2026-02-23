"""Memory framework types for Sophia."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class MemoryLevel(str, Enum):
    """Memory layers used by the agent."""

    PROCEDURAL = "procedural"
    LESSONS = "lessons"
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class MemoryLevelSpec:
    """Framework description for one memory level."""

    level: MemoryLevel
    purpose: str
    timeframe: str


MEMORY_LEVEL_SPECS: tuple[MemoryLevelSpec, ...] = (
    MemoryLevelSpec(
        level=MemoryLevel.PROCEDURAL,
        purpose="Agent behavior rules, style constraints, and operating policies.",
        timeframe="Weeks to months (changes only when configuration changes).",
    ),
    MemoryLevelSpec(
        level=MemoryLevel.LESSONS,
        purpose="Validated operating lessons learned from user corrections and stable directives.",
        timeframe="Weeks to months (durable, high-signal guidance).",
    ),
    MemoryLevelSpec(
        level=MemoryLevel.WORKING,
        purpose="Immediate conversational state and tool outputs for the current turn.",
        timeframe="Seconds to hours (rolling context window).",
    ),
    MemoryLevelSpec(
        level=MemoryLevel.EPISODIC,
        purpose="Compressed turn-level events: user intent, outcomes, and decisions.",
        timeframe="Days to weeks (session and near-session continuity).",
    ),
    MemoryLevelSpec(
        level=MemoryLevel.SEMANTIC,
        purpose="Durable facts, preferences, and stable project constraints.",
        timeframe="Weeks to months (persisted identity and decisions).",
    ),
)


@dataclass
class MemoryRecord:
    """One stored memory entry."""

    level: MemoryLevel
    content: str
    session_id: str | None = None
    tags: set[str] = field(default_factory=set)
    salience: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=utc_now)
    last_accessed_at: datetime | None = None
    access_count: int = 0

    def touch(self, at: datetime | None = None) -> None:
        """Update access stats when a record is retrieved."""
        self.last_accessed_at = at or utc_now()
        self.access_count += 1


@dataclass(frozen=True)
class MemoryMatch:
    """A memory record plus retrieval score."""

    record: MemoryRecord
    score: float


@dataclass(frozen=True)
class MemorySnapshot:
    """Grouped memory context prepared for prompt injection."""

    lessons: list[MemoryRecord]
    working_lines: list[str]
    episodic: list[MemoryRecord]
    semantic: list[MemoryRecord]

    def to_prompt_text(self) -> str:
        """Render memory snapshot as prompt-ready text."""
        parts: list[str] = [
            "Use relevant memory conservatively.",
            "Prioritize explicit user input in this turn over older memory.",
        ]

        if self.working_lines:
            parts.append("Working memory:")
            parts.extend(f"- {line}" for line in self.working_lines)

        if self.lessons:
            parts.append("Lessons memory:")
            parts.extend(f"- {rec.content}" for rec in self.lessons)

        if self.episodic:
            parts.append("Episodic memory:")
            parts.extend(f"- {rec.content}" for rec in self.episodic)

        if self.semantic:
            parts.append("Semantic memory:")
            parts.extend(f"- {rec.content}" for rec in self.semantic)

        if len(parts) == 2:
            return ""

        return "\n".join(parts)
