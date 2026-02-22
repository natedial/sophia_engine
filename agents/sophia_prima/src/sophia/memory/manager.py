"""Layered memory manager for Sophia."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sophia.llm.types import Message, Role
from sophia.memory.store import InMemoryMemoryStore, MemoryStore
from sophia.memory.types import MemoryLevel, MemoryRecord, MemorySnapshot, utc_now


@dataclass(frozen=True)
class MemoryManagerConfig:
    """Tunable retrieval and ingestion behavior."""

    enabled: bool = True
    working_window: int = 8
    episodic_recall_k: int = 3
    semantic_recall_k: int = 3
    max_item_chars: int = 240
    compaction_enabled: bool = True
    compaction_every_n_turns: int = 10
    compaction_max_episodic_per_session: int = 120
    compaction_batch_size: int = 40


class MemoryManager:
    """Coordinates memory ingestion, consolidation, and recall."""

    def __init__(
        self,
        store: MemoryStore | None = None,
        config: MemoryManagerConfig | None = None,
    ) -> None:
        self.store = store or InMemoryMemoryStore()
        self.config = config or MemoryManagerConfig()
        self._turns_since_compaction: dict[str, int] = {}

    def recall(
        self,
        *,
        session_id: str,
        query: str,
        messages: list[Message],
    ) -> MemorySnapshot:
        """Build a layered memory snapshot for the current query."""
        if not self.config.enabled:
            return MemorySnapshot(working_lines=[], episodic=[], semantic=[])

        working_lines = self._build_working_memory(messages)
        episodic = [
            m.record
            for m in self.store.query(
                session_id=session_id,
                query=query,
                levels={MemoryLevel.EPISODIC},
                limit=self.config.episodic_recall_k,
            )
        ]
        semantic = [
            m.record
            for m in self.store.query(
                session_id=session_id,
                query=query,
                levels={MemoryLevel.SEMANTIC},
                limit=self.config.semantic_recall_k,
            )
        ]
        return MemorySnapshot(
            working_lines=working_lines,
            episodic=episodic,
            semantic=semantic,
        )

    def recall_for_prompt(
        self,
        *,
        session_id: str,
        query: str,
        messages: list[Message],
    ) -> str:
        """Return prompt text for memory-conditioned generation."""
        return self.recall(
            session_id=session_id,
            query=query,
            messages=messages,
        ).to_prompt_text()

    def ingest_turn(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Persist episodic and semantic memory from a completed turn."""
        if not self.config.enabled:
            return

        user_text = user_message.strip()
        assistant_text = assistant_message.strip()
        if not user_text and not assistant_text:
            return

        self.store.add(
            MemoryRecord(
                level=MemoryLevel.EPISODIC,
                session_id=session_id,
                content=(
                    f"User asked: {self._truncate(user_text)} "
                    f"Assistant responded: {self._truncate(assistant_text)}"
                ).strip(),
                salience=self._estimate_salience(user_text),
                tags={"turn_summary"},
            )
        )

        for content, tags, salience in self._extract_semantic_facts(user_text):
            self.store.add(
                MemoryRecord(
                    level=MemoryLevel.SEMANTIC,
                    session_id=session_id,
                    content=self._truncate(content),
                    tags=tags,
                    salience=salience,
                )
            )

        if self.config.compaction_enabled:
            turns = self._turns_since_compaction.get(session_id, 0) + 1
            self._turns_since_compaction[session_id] = turns
            cadence = max(1, self.config.compaction_every_n_turns)
            if turns >= cadence:
                self.compact_session(session_id=session_id)
                self._turns_since_compaction[session_id] = 0

    def compact_session(self, *, session_id: str) -> None:
        """Compact older episodic records into a semantic summary and prune."""
        episodic = self.store.list_records(
            session_id=session_id,
            levels={MemoryLevel.EPISODIC},
            limit=None,
            newest_first=False,
        )
        count = len(episodic)
        if count <= self.config.compaction_max_episodic_per_session:
            return

        overflow = count - self.config.compaction_max_episodic_per_session
        batch_size = max(1, min(self.config.compaction_batch_size, count - 1))
        to_compact_count = min(batch_size, overflow if overflow > 0 else batch_size)
        compact_batch = episodic[:to_compact_count]
        if not compact_batch:
            return

        summary = self._build_compaction_summary(compact_batch, at=utc_now())
        self.store.add(
            MemoryRecord(
                level=MemoryLevel.SEMANTIC,
                session_id=session_id,
                content=summary,
                tags={"compaction", "episodic_summary"},
                salience=self._average_salience(compact_batch),
                metadata={
                    "source": "compaction",
                    "compacted_ids": [rec.id for rec in compact_batch],
                },
            )
        )
        self.store.delete_ids([rec.id for rec in compact_batch])

    def _build_working_memory(self, messages: list[Message]) -> list[str]:
        relevant: list[str] = []
        for msg in reversed(messages):
            if msg.role not in {Role.USER, Role.ASSISTANT}:
                continue
            if not msg.content:
                continue
            prefix = "User" if msg.role == Role.USER else "Assistant"
            relevant.append(f"{prefix}: {self._truncate(msg.content)}")
            if len(relevant) >= self.config.working_window:
                break
        relevant.reverse()
        return relevant

    def _extract_semantic_facts(self, text: str) -> list[tuple[str, set[str], float]]:
        facts: list[tuple[str, set[str], float]] = []

        patterns: list[tuple[str, str, float, str]] = [
            (
                r"\bmy name is ([A-Za-z][A-Za-z0-9 _'-]{1,40})\b",
                "identity",
                0.95,
                "User name is {value}.",
            ),
            (
                r"\bi (?:am|work as)\s+(?:an?\s+)?([A-Za-z][A-Za-z0-9 _'-]{1,60})\b",
                "profile",
                0.75,
                "User role/profile: {value}.",
            ),
            (
                r"\bi (?:prefer|like|love|dislike|avoid|want|need)\s+([^.!\n]{3,120})",
                "preference",
                0.8,
                "User preference: {value}.",
            ),
            (
                r"\bwe (?:decided|agreed|will|should)\s+([^.!\n]{3,160})",
                "decision",
                0.85,
                "Project decision: {value}.",
            ),
        ]

        lowered = text.strip()
        if not lowered:
            return facts

        for pattern, tag, salience, template in patterns:
            for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
                value = " ".join(match.group(1).split())
                if len(value) < 3:
                    continue
                facts.append((template.format(value=value), {tag}, salience))

        deduped: list[tuple[str, set[str], float]] = []
        seen: set[str] = set()
        for content, tags, salience in facts:
            key = content.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            deduped.append((content, tags, salience))
        return deduped

    def _build_compaction_summary(self, records: list[MemoryRecord], at: datetime) -> str:
        lines: list[str] = [
            f"Compaction summary at {at.isoformat()} for {len(records)} older turns:",
        ]
        for rec in records[:12]:
            lines.append(f"- {self._truncate(rec.content)}")
        if len(records) > 12:
            lines.append(f"- ... and {len(records) - 12} additional compacted turns.")
        return "\n".join(lines)

    @staticmethod
    def _average_salience(records: list[MemoryRecord]) -> float:
        if not records:
            return 0.6
        avg = sum(rec.salience for rec in records) / len(records)
        return min(max(avg, 0.4), 0.95)

    def _truncate(self, text: str) -> str:
        text = " ".join(text.split())
        if len(text) <= self.config.max_item_chars:
            return text
        return text[: self.config.max_item_chars] + "..."

    @staticmethod
    def _estimate_salience(user_text: str) -> float:
        lower = user_text.lower()
        score = 0.45
        keywords = ("always", "never", "important", "remember", "decision", "preference")
        for kw in keywords:
            if kw in lower:
                score += 0.1
        return min(score, 0.95)
