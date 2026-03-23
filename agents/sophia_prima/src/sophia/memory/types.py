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

    def to_prompt_text(self, max_chars: int | None = None) -> str:
        """Render memory snapshot as prompt-ready text.

        Args:
            max_chars: Optional character limit. If set, trim content from
                lowest-salience records first (semantic, then episodic, then
                working). Never drop lessons. If lessons alone exceed budget,
                truncate the final output with a marker.
        """
        parts: list[str] = [
            "Use relevant memory conservatively.",
            "Prioritize explicit user input in this turn over older memory.",
        ]
        if self._split_semantic(self.semantic)[0]:
            parts.append(
                "When Resource memory is relevant, treat those links as user-endorsed starting points "
                "for sourcing, but still verify freshness and applicability before relying on them."
            )
        parts.extend(
            self._rebuild_parts(
                semantic=self.semantic,
                episodic=self.episodic,
                working=self.working_lines,
                include_preamble=False,
            )
        )

        if len(parts) == 2:
            return ""

        text = "\n".join(parts)

        if max_chars is None or len(text) <= max_chars:
            return text

        return self._trim_to_budget(parts, max_chars)

    def _trim_to_budget(self, parts: list[str], max_chars: int) -> str:
        resource_semantic, general_semantic = self._split_semantic(self.semantic)
        episodic = self.episodic.copy()
        working = self.working_lines.copy()

        while len("\n".join(parts)) > max_chars and (
            general_semantic or resource_semantic or episodic or working
        ):
            if general_semantic:
                general_semantic.pop()
            elif resource_semantic:
                resource_semantic.pop()
            elif episodic:
                episodic.pop()
            elif working:
                working.pop(0)
            else:
                break

            parts = self._rebuild_parts(
                semantic=[*resource_semantic, *general_semantic],
                episodic=episodic,
                working=working,
            )

        text = "\n".join(parts)
        if len(text) > max_chars:
            lessons_text = self._render_lessons()
            budget_for_rest = max_chars - len(lessons_text) - 30
            if budget_for_rest > 100:
                text = lessons_text + "\n... [memory truncated]"
            else:
                text = lessons_text[:max_chars]

        return text

    def _rebuild_parts(
        self,
        semantic: list[MemoryRecord],
        episodic: list[MemoryRecord],
        working: list[str],
        *,
        include_preamble: bool = True,
    ) -> list[str]:
        parts: list[str] = []
        if include_preamble:
            parts.extend(
                [
                    "Use relevant memory conservatively.",
                    "Prioritize explicit user input in this turn over older memory.",
                ]
            )

        if working:
            parts.append("Working memory:")
            parts.extend(f"- {line}" for line in working)

        if self.lessons:
            parts.append("Lessons memory:")
            parts.extend(f"- {rec.content}" for rec in self.lessons)

        if episodic:
            parts.append("Episodic memory:")
            parts.extend(f"- {rec.content}" for rec in episodic)

        resource_semantic, general_semantic = self._split_semantic(semantic)
        if resource_semantic:
            parts.append("Resource memory:")
            parts.extend(f"- {rec.content}" for rec in resource_semantic)

        if general_semantic:
            parts.append("Semantic memory:")
            parts.extend(f"- {rec.content}" for rec in general_semantic)

        return parts

    def _render_lessons(self) -> str:
        parts: list[str] = [
            "Use relevant memory conservatively.",
            "Prioritize explicit user input in this turn over older memory.",
        ]
        if self.lessons:
            parts.append("Lessons memory:")
            parts.extend(f"- {rec.content}" for rec in self.lessons)
        return "\n".join(parts)

    @staticmethod
    def _split_semantic(
        semantic: list[MemoryRecord],
    ) -> tuple[list[MemoryRecord], list[MemoryRecord]]:
        resource_semantic: list[MemoryRecord] = []
        general_semantic: list[MemoryRecord] = []
        for record in semantic:
            if record.metadata.get("source") == "user_endorsed_resource" or "resource" in record.tags:
                resource_semantic.append(record)
                continue
            general_semantic.append(record)
        return resource_semantic, general_semantic


@dataclass(frozen=True)
class FrozenMemorySnapshot:
    """Frozen memory snapshot for a single turn.

    This is a value object that captures memory at a point in time,
    ensuring the prompt doesn't change during inner-loop iterations.
    """

    rendered_text: str
    created_at: datetime
    session_id: str
    query: str
