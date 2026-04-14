"""Layered memory manager for Sophia."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from sophia.llm.types import Message, Role
from sophia.memory.store import InMemoryMemoryStore, MemoryStore, score_records
from sophia.memory.types import (
    FrozenMemorySnapshot,
    MemoryLevel,
    MemoryMatch,
    MemoryRecord,
    MemorySnapshot,
    utc_now,
)


@dataclass(frozen=True)
class MemoryManagerConfig:
    """Tunable retrieval and ingestion behavior."""

    enabled: bool = True
    working_window: int = 8
    lessons_recall_k: int = 4
    episodic_recall_k: int = 3
    semantic_recall_k: int = 3
    resource_recall_k: int = 2
    lesson_promotion_min_repeats: int = 2
    max_item_chars: int = 240
    max_snapshot_chars: int = 3000
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
        seed_lessons: list[str] | None = None,
    ) -> None:
        self.store = store or InMemoryMemoryStore()
        self.config = config or MemoryManagerConfig()
        self._turns_since_compaction: dict[str, int] = {}
        self._lesson_candidate_counts: dict[tuple[str, str], int] = {}
        self._known_lessons: dict[str, set[str]] = {}
        self._seed_lesson_records: list[MemoryRecord] = []
        self._set_seed_lessons(seed_lessons or [])

    def set_seed_lessons(self, lessons: list[str]) -> None:
        """Replace seed lessons (typically loaded from LESSONS.md)."""
        self._set_seed_lessons(lessons)

    def recall(
        self,
        *,
        session_id: str,
        query: str,
        messages: list[Message],
    ) -> MemorySnapshot:
        """Build a layered memory snapshot for the current query."""
        if not self.config.enabled:
            return MemorySnapshot(lessons=[], working_lines=[], episodic=[], semantic=[])

        working_lines = self._build_working_memory(messages)
        lessons = self._build_lessons_memory(session_id=session_id, query=query)
        episodic = [
            m.record
            for m in self.store.query(
                session_id=session_id,
                query=query,
                levels={MemoryLevel.EPISODIC},
                limit=self.config.episodic_recall_k,
            )
        ]
        resource_semantic = self._query_semantic_records(
            session_id=session_id,
            query=query,
            limit=self.config.resource_recall_k,
            resources_only=True,
        )
        general_semantic = self._query_semantic_records(
            session_id=session_id,
            query=query,
            limit=self.config.semantic_recall_k,
            resources_only=False,
        )
        semantic = resource_semantic + general_semantic
        return MemorySnapshot(
            lessons=lessons,
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

    def freeze_for_turn(
        self,
        *,
        session_id: str,
        query: str,
        messages: list[Message],
    ) -> FrozenMemorySnapshot:
        """Build a frozen memory snapshot for the current turn.

        This captures memory once per outer turn, ensuring the prompt
        remains stable during inner-loop iterations while still
        reflecting the latest conversation state.
        """
        snapshot = self.recall(
            session_id=session_id,
            query=query,
            messages=messages,
        )
        text = snapshot.to_prompt_text(max_chars=self.config.max_snapshot_chars)
        return FrozenMemorySnapshot(
            rendered_text=text,
            created_at=utc_now(),
            session_id=session_id,
            query=query,
        )

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

        self._promote_lesson_candidates(
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
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

        for record in self._extract_resource_memories(user_text):
            if self._resource_memory_exists(record.metadata.get("url")):
                continue
            self.store.add(record)

        if self.config.compaction_enabled:
            turns = self._turns_since_compaction.get(session_id, 0) + 1
            self._turns_since_compaction[session_id] = turns
            cadence = max(1, self.config.compaction_every_n_turns)
            if turns >= cadence:
                self.compact_session(session_id=session_id)
                self._turns_since_compaction[session_id] = 0

    def _build_lessons_memory(self, *, session_id: str, query: str) -> list[MemoryRecord]:
        limit = max(0, self.config.lessons_recall_k)
        if limit == 0:
            return []

        persisted_lessons = [
            m.record
            for m in self.store.query(
                session_id=session_id,
                query=query,
                levels={MemoryLevel.LESSONS},
                limit=limit,
            )
        ]
        lessons: list[MemoryRecord] = []
        seen: set[str] = set()
        for rec in self._seed_lesson_records:
            norm = self._normalize_lesson(rec.content)
            if norm in seen:
                continue
            lessons.append(rec)
            seen.add(norm)
            if len(lessons) >= limit:
                return lessons

        for rec in persisted_lessons:
            norm = self._normalize_lesson(rec.content)
            if norm in seen:
                continue
            lessons.append(rec)
            seen.add(norm)
            if len(lessons) >= limit:
                break
        return lessons

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

    async def compact_session_with_model(
        self,
        *,
        session_id: str,
        summarizer: Callable[[str], Awaitable[str]],
    ) -> bool:
        """Compact using an LLM for higher-quality summaries.

        This runs asynchronously and does not block the user-facing path.
        Falls back to heuristic compaction if the summarizer fails.
        """
        episodic = self.store.list_records(
            session_id=session_id,
            levels={MemoryLevel.EPISODIC},
            limit=None,
            newest_first=False,
        )
        count = len(episodic)
        if count <= self.config.compaction_max_episodic_per_session:
            return False

        overflow = count - self.config.compaction_max_episodic_per_session
        batch_size = max(1, min(self.config.compaction_batch_size, count - 1))
        to_compact_count = min(batch_size, overflow if overflow > 0 else batch_size)
        compact_batch = episodic[:to_compact_count]
        if not compact_batch:
            return False

        transcript = "\n".join(f"- {rec.content}" for rec in compact_batch)

        try:
            summary = await summarizer(transcript)
            if not summary or not summary.strip():
                raise ValueError("Empty summary returned")
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "model_compaction_failed session_id=%s, falling back to heuristic",
                session_id,
            )
            self.compact_session(session_id=session_id)
            return False

        self.store.add(
            MemoryRecord(
                level=MemoryLevel.SEMANTIC,
                session_id=session_id,
                content=summary,
                tags={"compaction", "episodic_summary", "model_generated"},
                salience=self._average_salience(compact_batch),
                metadata={
                    "source": "compaction_llm",
                    "compacted_ids": [rec.id for rec in compact_batch],
                },
            )
        )
        self.store.delete_ids([rec.id for rec in compact_batch])
        return True

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
                r"\bi do not (?:typically\s+|generally\s+)?care about\s+([^\n]{3,200})",
                "preference",
                0.85,
                "User preference: do not care about {value}.",
            ),
            (
                r"\bi (?:generally\s+|typically\s+)?care about\s+([^\n]{3,200})",
                "preference",
                0.82,
                "User preference: care about {value}.",
            ),
            (
                r"\bi (?:prefer|like|love|dislike|avoid|want|need)\s+([^\n]{3,160})",
                "preference",
                0.8,
                "User preference: {value}.",
            ),
            (
                r"\bwe (?:decided|agreed|will|should)\s+([^\n]{3,200})",
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
                value = self._clean_clause(match.group(1)).rstrip(".!?")
                if len(value) < 3:
                    continue
                facts.append((template.format(value=value), {tag}, salience))

        facts.extend(self._extract_preference_block_facts(lowered))

        deduped: list[tuple[str, set[str], float]] = []
        seen: set[str] = set()
        for content, tags, salience in facts:
            key = content.lower().strip()
            if key in seen:
                continue
            seen.add(key)
            deduped.append((content, tags, salience))
        return deduped

    def _extract_preference_block_facts(
        self,
        text: str,
    ) -> list[tuple[str, set[str], float]]:
        lines = [line.rstrip() for line in text.splitlines()]
        if not lines:
            return []

        facts: list[tuple[str, set[str], float]] = []
        idx = 0
        while idx < len(lines):
            line = lines[idx].strip()
            if not line:
                idx += 1
                continue

            polarity: str | None = None
            remainder = ""

            negative = re.match(
                r"^i do not (?:typically\s+|generally\s+)?care about:\s*(.*)$",
                line,
                flags=re.IGNORECASE,
            )
            positive = re.match(
                r"^i (?:generally\s+|typically\s+)?care about:\s*(.*)$",
                line,
                flags=re.IGNORECASE,
            )

            if negative:
                polarity = "do not care about"
                remainder = negative.group(1).strip()
            elif positive:
                polarity = "care about"
                remainder = positive.group(1).strip()

            if polarity is None:
                idx += 1
                continue

            items: list[str] = []
            if remainder:
                items.append(remainder)

            next_idx = idx + 1
            while next_idx < len(lines):
                candidate = lines[next_idx].strip()
                if not candidate:
                    break
                if re.match(r"^i\b", candidate, flags=re.IGNORECASE):
                    break
                cleaned = re.sub(r"^[\-\*\u2022\d\.\)\s]+", "", candidate).strip()
                if cleaned:
                    items.append(cleaned)
                next_idx += 1

            for item in items:
                normalized = " ".join(item.split())
                if len(normalized) < 3:
                    continue
                facts.append(
                    (
                        f"User preference: {polarity} {normalized}.",
                        {"preference"},
                        0.82 if polarity == "care about" else 0.85,
                    )
                )

            idx = next_idx if next_idx > idx else idx + 1

        return facts

    def _query_semantic_records(
        self,
        *,
        session_id: str,
        query: str,
        limit: int,
        resources_only: bool,
    ) -> list[MemoryRecord]:
        if limit <= 0:
            return []

        records = self.store.list_records(
            session_id=session_id,
            levels={MemoryLevel.SEMANTIC},
            limit=400,
            newest_first=True,
        )
        filtered = [
            record
            for record in records
            if self._is_resource_record(record) is resources_only
        ]
        if not filtered:
            return []

        matches = score_records(
            records=filtered,
            session_id=session_id,
            query=query,
            limit=limit,
            now=utc_now(),
            semantic_search_enabled=getattr(self.store, "_semantic_search_enabled", True),
            lexical_weight=getattr(self.store, "_lexical_weight", 0.45),
            semantic_weight=getattr(self.store, "_semantic_weight", 0.35),
        )
        self._touch_matches(matches)
        return [match.record for match in matches]

    def _extract_resource_memories(self, text: str) -> list[MemoryRecord]:
        stripped = text.strip()
        if not stripped:
            return []

        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            return []

        endorsed_urls: list[tuple[str, int]] = []
        seen_urls: set[str] = set()
        for idx, line in enumerate(lines):
            if not self._looks_like_resource_intro(line):
                continue

            for url in self._extract_urls(line):
                if url not in seen_urls:
                    endorsed_urls.append((url, idx))
                    seen_urls.add(url)

            for follow_idx in range(idx + 1, len(lines)):
                follow_line = lines[follow_idx]
                urls = self._extract_urls(follow_line)
                if urls:
                    for url in urls:
                        if url in seen_urls:
                            continue
                        endorsed_urls.append((url, idx))
                        seen_urls.add(url)
                    continue
                break

        records: list[MemoryRecord] = []
        for url, intro_idx in endorsed_urls:
            topic_hint = self._build_resource_topic_hint(lines[:intro_idx])
            content = f"User-endorsed resource: {url}."
            if topic_hint:
                content = f"User-endorsed resource for {topic_hint}: {url}."

            metadata = {
                "source": "user_endorsed_resource",
                "url": url,
                "user_endorsed": True,
            }
            if topic_hint:
                metadata["topic_hint"] = topic_hint

            records.append(
                MemoryRecord(
                    level=MemoryLevel.SEMANTIC,
                    session_id=None,
                    content=self._truncate(content),
                    tags={"resource", "user_endorsed_source", "link"},
                    salience=0.88,
                    metadata=metadata,
                )
            )
        return records

    def _promote_lesson_candidates(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
    ) -> None:
        candidates = self._extract_lesson_candidates(
            user_text=user_text,
            assistant_text=assistant_text,
        )
        if not candidates:
            return

        known = self._known_lessons_for_session(session_id)
        repeat_threshold = max(1, self.config.lesson_promotion_min_repeats)

        for candidate_text, explicit in candidates:
            lesson = self._truncate(candidate_text)
            normalized = self._normalize_lesson(lesson)
            if not normalized or normalized in known:
                continue

            key = (session_id, normalized)
            count = self._lesson_candidate_counts.get(key, 0) + 1
            self._lesson_candidate_counts[key] = count

            if not explicit and count < repeat_threshold:
                continue

            confidence = 0.9 if explicit else min(0.75 + (count * 0.05), 0.9)
            self.store.add(
                MemoryRecord(
                    level=MemoryLevel.LESSONS,
                    session_id=session_id,
                    content=f"Lesson: {lesson}",
                    tags={"lesson", "promoted", "explicit" if explicit else "repeated"},
                    salience=confidence,
                    metadata={
                        "source": "promotion",
                        "explicit": explicit,
                        "repeat_count": count,
                    },
                )
            )
            known.add(normalized)

    def _extract_lesson_candidates(
        self,
        *,
        user_text: str,
        assistant_text: str,
    ) -> list[tuple[str, bool]]:
        out: list[tuple[str, bool]] = []
        text = user_text.strip()
        if not text:
            return out

        explicit_patterns = [
            r"\bfrom now on[,:\s-]*(.+)",
            r"\b(?:please\s+)?remember(?:\s+(?:this|that))?[:\s-]*(.+)",
            r"\balways\s+(.+)",
            r"\bnever\s+(.+)",
        ]
        for pattern in explicit_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            clause = self._clean_clause(match.group(1))
            if clause:
                out.append((clause, True))

        correction_prefixes = (
            "that's wrong",
            "that is wrong",
            "not correct",
            "no, ",
            "incorrect",
        )
        lower = text.lower()
        if any(lower.startswith(prefix) for prefix in correction_prefixes):
            cleaned = self._clean_clause(text)
            if cleaned:
                out.append((cleaned, True))

        # Repeated preference/decision signals can graduate into lessons
        for content, tags, _salience in self._extract_semantic_facts(text):
            if "preference" in tags or "decision" in tags:
                out.append((content, False))

        deduped: list[tuple[str, bool]] = []
        seen: set[str] = set()
        for content, explicit in out:
            key = self._normalize_lesson(content)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append((content, explicit))
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

    def _resource_memory_exists(self, url: object) -> bool:
        if not isinstance(url, str) or not url:
            return False
        existing = self.store.search_by_substring(
            substring=url,
            session_id=None,
            levels={MemoryLevel.SEMANTIC},
        )
        for record in existing:
            if record.metadata.get("source") == "user_endorsed_resource":
                return True
        return False

    def _touch_matches(self, matches: list[MemoryMatch]) -> None:
        now = utc_now()
        if hasattr(self.store, "_touch"):
            touch = getattr(self.store, "_touch")
            try:
                touch([match.record for match in matches], now)
                return
            except Exception:
                logging.getLogger(__name__).debug("memory_touch_matches_failed", exc_info=True)
        for match in matches:
            match.record.touch(now)

    @staticmethod
    def _is_resource_record(record: MemoryRecord) -> bool:
        return record.metadata.get("source") == "user_endorsed_resource" or "resource" in record.tags

    def _set_seed_lessons(self, lessons: list[str]) -> None:
        self._seed_lesson_records = []
        for raw in lessons:
            text = self._clean_clause(raw)
            if not text:
                continue
            self._seed_lesson_records.append(
                MemoryRecord(
                    level=MemoryLevel.LESSONS,
                    session_id=None,
                    content=f"Lesson: {text}",
                    tags={"lesson", "seed"},
                    salience=0.95,
                    metadata={"source": "LESSONS.md"},
                )
            )
        self._known_lessons.clear()

    def _known_lessons_for_session(self, session_id: str) -> set[str]:
        cached = self._known_lessons.get(session_id)
        if cached is not None:
            return cached

        known = {self._normalize_lesson(rec.content) for rec in self._seed_lesson_records}
        records = self.store.list_records(
            session_id=session_id,
            levels={MemoryLevel.LESSONS},
            limit=None,
            newest_first=True,
        )
        known.update(self._normalize_lesson(rec.content) for rec in records)
        known.discard("")
        self._known_lessons[session_id] = known
        return known

    @staticmethod
    def _normalize_lesson(text: str) -> str:
        normalized = text.strip().lower()
        if normalized.startswith("lesson:"):
            normalized = normalized[len("lesson:") :].strip()
        return " ".join(normalized.split())

    def _clean_clause(self, text: str) -> str:
        stripped = text.strip()
        stripped = re.sub(r"^[\-\*\d\.\)\s]+", "", stripped)
        stripped = re.split(r"[.!?]\s", stripped, maxsplit=1)[0]
        stripped = stripped.strip(" -:\t\n")
        return self._truncate(stripped)

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        return re.findall(r"https?://[^\s<>\"]+", text)

    @staticmethod
    def _looks_like_resource_intro(text: str) -> bool:
        normalized = " ".join(text.lower().split())
        if not normalized:
            return False
        markers = (
            "good resource",
            "good resources",
            "helpful resource",
            "helpful resources",
            "useful resource",
            "useful resources",
            "good source",
            "good sources",
            "helpful source",
            "helpful sources",
            "useful source",
            "useful sources",
            "reference link",
            "reference links",
            "resource for this",
            "resources for this",
            "source for this",
            "sources for this",
        )
        return any(marker in normalized for marker in markers)

    def _build_resource_topic_hint(self, lines: list[str]) -> str:
        context_lines = [line for line in lines if not self._extract_urls(line)]
        if not context_lines:
            return ""
        hint = " ".join(context_lines[-2:])
        hint = re.sub(r"^(can|could|would)\s+you\s+", "", hint, flags=re.IGNORECASE)
        hint = re.sub(r"^please\s+", "", hint, flags=re.IGNORECASE)
        hint = hint.strip(" .:?")
        hint = " ".join(hint.split())
        return self._truncate(hint)
