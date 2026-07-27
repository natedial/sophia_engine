"""Memory storage and retrieval primitives."""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from sophia.memory.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    cosine_sparse,
    create_embedding_provider,
    deserialize_sparse_vector,
    hash_semantic_vector,
    serialize_sparse_vector,
)
from sophia.memory.types import MemoryLevel, MemoryMatch, MemoryRecord, utc_now

logger = logging.getLogger(__name__)


class MemoryStore(Protocol):
    """Interface for memory storage implementations."""

    def add(self, record: MemoryRecord) -> None:
        """Store one memory record."""

    def query(
        self,
        *,
        session_id: str,
        query: str,
        levels: set[MemoryLevel],
        limit: int,
    ) -> list[MemoryMatch]:
        """Retrieve top memory matches for a query."""

    def list_records(
        self,
        *,
        session_id: str | None = None,
        levels: set[MemoryLevel] | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> list[MemoryRecord]:
        """List records for maintenance operations such as compaction."""

    def delete_ids(self, ids: list[str]) -> None:
        """Delete records by id."""

    def index_pending_embeddings(
        self,
        *,
        batch_size: int,
        max_batches: int,
    ) -> dict[str, int]:
        """Index pending embeddings asynchronously (if supported)."""

    def search_by_substring(
        self,
        *,
        substring: str,
        session_id: str | None = None,
        levels: set[MemoryLevel] | None = None,
    ) -> list[MemoryRecord]:
        """Search records by substring match (case-insensitive)."""


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]{3,}", text.lower()))


def _age_hours(since: datetime, now: datetime) -> float:
    return max(0.0, (now - since).total_seconds() / 3600.0)


_EMBEDDING_STATUS_PENDING = "pending"
_EMBEDDING_STATUS_READY = "ready"
_EMBEDDING_STATUS_FAILED = "failed"
_EMBEDDING_STATUS_SKIPPED = "skipped"


class InMemoryMemoryStore:
    """Simple in-process store with lexical + recency scoring."""

    def __init__(
        self,
        now_fn: Callable[[], datetime] | None = None,
        *,
        semantic_search_enabled: bool = True,
        lexical_weight: float = 0.45,
        semantic_weight: float = 0.35,
    ) -> None:
        self._records: list[MemoryRecord] = []
        self._now_fn = now_fn or utc_now
        self._semantic_search_enabled = semantic_search_enabled
        self._lexical_weight = lexical_weight
        self._semantic_weight = semantic_weight

    def add(self, record: MemoryRecord) -> None:
        self._records.append(record)

    def query(
        self,
        *,
        session_id: str,
        query: str,
        levels: set[MemoryLevel],
        limit: int,
    ) -> list[MemoryMatch]:
        now = self._now_fn()
        records = self.list_records(session_id=session_id, levels=levels, limit=None)
        top = score_records(
            records=records,
            session_id=session_id,
            query=query,
            limit=limit,
            now=now,
            semantic_search_enabled=self._semantic_search_enabled,
            lexical_weight=self._lexical_weight,
            semantic_weight=self._semantic_weight,
        )
        for match in top:
            match.record.touch(now)
        return top

    def list_records(
        self,
        *,
        session_id: str | None = None,
        levels: set[MemoryLevel] | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> list[MemoryRecord]:
        out: list[MemoryRecord] = []
        for rec in self._records:
            if levels and rec.level not in levels:
                continue
            if session_id is not None and rec.session_id is not None and rec.session_id != session_id:
                continue
            out.append(rec)

        out.sort(key=lambda rec: rec.created_at, reverse=newest_first)
        if limit is not None:
            return out[:limit]
        return out

    def delete_ids(self, ids: list[str]) -> None:
        id_set = set(ids)
        if not id_set:
            return
        self._records = [rec for rec in self._records if rec.id not in id_set]

    def index_pending_embeddings(
        self,
        *,
        batch_size: int,
        max_batches: int,
    ) -> dict[str, int]:
        return {
            "processed": 0,
            "ready": 0,
            "failed": 0,
            "batches": 0,
            "backlog_before": 0,
            "backlog_after": 0,
        }

    def search_by_substring(
        self,
        *,
        substring: str,
        session_id: str | None = None,
        levels: set[MemoryLevel] | None = None,
    ) -> list[MemoryRecord]:
        """Search records by substring match (case-insensitive)."""
        if not substring:
            return []
        lower_substring = substring.lower()
        results = []
        for rec in self._records:
            if levels and rec.level not in levels:
                continue
            if session_id is not None and rec.session_id != session_id:
                continue
            if lower_substring in rec.content.lower():
                results.append(rec)
        return results


class SQLiteMemoryStore:
    """Persistent memory store backed by SQLite."""

    def __init__(
        self,
        db_path: str | Path,
        now_fn: Callable[[], datetime] | None = None,
        *,
        semantic_search_enabled: bool = True,
        lexical_weight: float = 0.45,
        semantic_weight: float = 0.35,
        embedding_model: str = "hash-v1",
        embedding_enabled: bool = True,
        embed_episodic: bool = True,
        embed_semantic: bool = True,
        query_use_embedding_index: bool = True,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._now_fn = now_fn or utc_now
        self._semantic_search_enabled = semantic_search_enabled
        self._lexical_weight = lexical_weight
        self._semantic_weight = semantic_weight
        self._embedding_model = embedding_model
        self._embedding_enabled = embedding_enabled
        self._query_use_embedding_index = query_use_embedding_index
        self._embedding_provider = embedding_provider
        if self._embedding_provider is None and self._embedding_enabled:
            self._embedding_provider = HashEmbeddingProvider(model_name=self._embedding_model)
        self._embed_levels: set[MemoryLevel] = set()
        if embed_episodic:
            self._embed_levels.add(MemoryLevel.EPISODIC)
        if embed_semantic:
            self._embed_levels.add(MemoryLevel.SEMANTIC)
            self._embed_levels.add(MemoryLevel.LESSONS)
        self._ensure_schema()

    def add(self, record: MemoryRecord) -> None:
        embedding_status = _EMBEDDING_STATUS_SKIPPED
        if self._embedding_enabled and record.level in self._embed_levels:
            embedding_status = _EMBEDDING_STATUS_PENDING

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_records (
                    id, level, content, session_id, tags, salience, metadata,
                    created_at, last_accessed_at, access_count,
                    embedding_status, embedding_updated_at, embedding_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.level.value,
                    record.content,
                    record.session_id,
                    json.dumps(sorted(record.tags)),
                    float(record.salience),
                    json.dumps(record.metadata),
                    record.created_at.isoformat(),
                    record.last_accessed_at.isoformat() if record.last_accessed_at else None,
                    int(record.access_count),
                    embedding_status,
                    None,
                    None,
                ),
            )
            conn.commit()

    def query(
        self,
        *,
        session_id: str,
        query: str,
        levels: set[MemoryLevel],
        limit: int,
    ) -> list[MemoryMatch]:
        candidates = self.list_records(
            session_id=session_id,
            levels=levels,
            limit=1200,
            newest_first=True,
        )
        now = self._now_fn()
        semantic_scores: dict[str, float] | None = None
        if self._embedding_enabled and self._query_use_embedding_index and candidates:
            query_vec = self._embed_query(query)
            if query_vec:
                stored = self._load_embeddings_by_record_ids(
                    [rec.id for rec in candidates],
                    model=self._embedding_model,
                )
                if stored:
                    semantic_scores = {
                        rec_id: cosine_sparse(query_vec, rec_vec)
                        for rec_id, rec_vec in stored.items()
                    }
                else:
                    logger.debug(
                        "memory_query_no_indexed_vectors model=%s candidates=%s",
                        self._embedding_model,
                        len(candidates),
                    )
            else:
                logger.debug(
                    "memory_query_no_query_embedding model=%s provider=%s",
                    self._embedding_model,
                    self._embedding_provider.name if self._embedding_provider else "none",
                )

        top = score_records(
            records=candidates,
            session_id=session_id,
            query=query,
            limit=limit,
            now=now,
            semantic_scores_by_id=semantic_scores,
            semantic_search_enabled=self._semantic_search_enabled,
            lexical_weight=self._lexical_weight,
            semantic_weight=self._semantic_weight,
        )
        self._touch([match.record for match in top], now)
        logger.debug(
            "memory_query_done model=%s candidates=%s matched=%s indexed_semantic=%s",
            self._embedding_model,
            len(candidates),
            len(top),
            semantic_scores is not None,
        )
        return top

    def list_records(
        self,
        *,
        session_id: str | None = None,
        levels: set[MemoryLevel] | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> list[MemoryRecord]:
        where: list[str] = []
        params: list[object] = []

        if session_id is not None:
            where.append("(session_id = ? OR session_id IS NULL)")
            params.append(session_id)

        if levels:
            level_values = [level.value for level in levels]
            placeholders = ", ".join("?" for _ in level_values)
            where.append(f"level IN ({placeholders})")
            params.extend(level_values)

        order = "DESC" if newest_first else "ASC"
        sql = (
            "SELECT id, level, content, session_id, tags, salience, metadata, "
            "created_at, last_accessed_at, access_count "
            "FROM memory_records "
        f"ORDER BY created_at {order}"
        )
        if where:
            sql = (
                "SELECT id, level, content, session_id, tags, salience, metadata, "
                "created_at, last_accessed_at, access_count "
                "FROM memory_records "
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY created_at {order}"
            )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        with self._connect() as conn:
            conn.execute(f"DELETE FROM memory_records WHERE id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM memory_embeddings WHERE record_id IN ({placeholders})", ids)
            conn.commit()

    def index_pending_embeddings(
        self,
        *,
        batch_size: int,
        max_batches: int,
    ) -> dict[str, int]:
        if not self._embedding_enabled:
            return {
                "processed": 0,
                "ready": 0,
                "failed": 0,
                "batches": 0,
                "backlog_before": 0,
                "backlog_after": 0,
            }

        if self._embedding_provider is None:
            logger.warning("Embedding index requested but no embedding provider configured.")
            return {
                "processed": 0,
                "ready": 0,
                "failed": 0,
                "batches": 0,
                "backlog_before": self._count_pending_records(),
                "backlog_after": self._count_pending_records(),
            }

        limit = max(1, batch_size)
        max_loops = max(1, max_batches)
        backlog_before = self._count_pending_records()
        stats = {
            "processed": 0,
            "ready": 0,
            "failed": 0,
            "batches": 0,
            "backlog_before": backlog_before,
            "backlog_after": backlog_before,
        }
        logger.info(
            "memory_index_start provider=%s model=%s backlog=%s batch_size=%s max_batches=%s",
            self._embedding_provider.name,
            self._embedding_model,
            backlog_before,
            limit,
            max_loops,
        )

        for _ in range(max_loops):
            pending = self._fetch_pending_records(limit=limit)
            if not pending:
                break
            stats["batches"] += 1
            ids = [str(row["id"]) for row in pending]
            texts = [str(row["content"]) for row in pending]

            try:
                vectors = self._embedding_provider.embed_texts(texts)
                if len(vectors) != len(pending):
                    raise RuntimeError(
                        f"Embedding provider returned {len(vectors)} vectors for {len(pending)} records."
                    )
            except Exception as exc:
                with self._connect() as conn:
                    for rec_id in ids:
                        conn.execute(
                            """
                            UPDATE memory_records
                            SET embedding_status = ?, embedding_error = ?
                            WHERE id = ?
                            """,
                            (_EMBEDDING_STATUS_FAILED, str(exc), rec_id),
                        )
                        stats["failed"] += 1
                        stats["processed"] += 1
                    conn.commit()
                logger.exception(
                    "memory_index_batch_failed provider=%s model=%s count=%s",
                    self._embedding_provider.name,
                    self._embedding_model,
                    len(ids),
                )
                continue

            with self._connect() as conn:
                for row, embedding in zip(pending, vectors, strict=True):
                    rec_id = str(row["id"])
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO memory_embeddings (
                            record_id, model, vector_json, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            rec_id,
                            self._embedding_model,
                            serialize_sparse_vector(embedding),
                            self._now_fn().isoformat(),
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE memory_records
                        SET embedding_status = ?, embedding_updated_at = ?, embedding_error = NULL
                        WHERE id = ?
                        """,
                        (
                            _EMBEDDING_STATUS_READY,
                            self._now_fn().isoformat(),
                            rec_id,
                        ),
                    )
                    stats["ready"] += 1
                    stats["processed"] += 1
                conn.commit()
            logger.info(
                "memory_index_batch provider=%s model=%s processed=%s ready=%s failed=%s",
                self._embedding_provider.name,
                self._embedding_model,
                stats["processed"],
                stats["ready"],
                stats["failed"],
            )

        stats["backlog_after"] = self._count_pending_records()
        logger.info(
            "memory_index_done provider=%s model=%s processed=%s ready=%s failed=%s batches=%s backlog_before=%s backlog_after=%s",
            self._embedding_provider.name if self._embedding_provider else "none",
            self._embedding_model,
            stats["processed"],
            stats["ready"],
            stats["failed"],
            stats["batches"],
            stats["backlog_before"],
            stats["backlog_after"],
        )
        return stats

    def search_by_substring(
        self,
        *,
        substring: str,
        session_id: str | None = None,
        levels: set[MemoryLevel] | None = None,
    ) -> list[MemoryRecord]:
        """Search records by substring match (case-insensitive)."""
        if not substring:
            return []

        where = ["content LIKE ?"]
        params: list[object] = [f"%{substring}%"]

        if session_id is not None:
            where.append("(session_id = ? OR session_id IS NULL)")
            params.append(session_id)

        if levels:
            level_values = [level.value for level in levels]
            placeholders = ", ".join("?" for _ in level_values)
            where.append(f"level IN ({placeholders})")
            params.extend(level_values)

        sql = (
            "SELECT id, level, content, session_id, tags, salience, metadata, "
            "created_at, last_accessed_at, access_count "
            "FROM memory_records "
            f"WHERE {' AND '.join(where)}"
        )

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _embed_query(self, query: str) -> dict[int, float]:
        if self._embedding_provider is None:
            return {}
        try:
            vectors = self._embedding_provider.embed_texts([query])
            return vectors[0] if vectors else {}
        except Exception:
            logger.exception(
                "memory_query_embedding_failed provider=%s model=%s",
                self._embedding_provider.name,
                self._embedding_model,
            )
            return {}

    def _touch(self, records: list[MemoryRecord], now: datetime) -> None:
        if not records:
            return
        with self._connect() as conn:
            for rec in records:
                rec.touch(now)
                conn.execute(
                    """
                    UPDATE memory_records
                    SET last_accessed_at = ?, access_count = ?
                    WHERE id = ?
                    """,
                    (
                        rec.last_accessed_at.isoformat() if rec.last_accessed_at else None,
                        rec.access_count,
                        rec.id,
                    ),
                )
            conn.commit()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    level TEXT NOT NULL,
                    content TEXT NOT NULL,
                    session_id TEXT,
                    tags TEXT NOT NULL,
                    salience REAL NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_accessed_at TEXT,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    embedding_status TEXT NOT NULL DEFAULT 'pending',
                    embedding_updated_at TEXT,
                    embedding_error TEXT
                )
                """
            )
            self._ensure_record_columns(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    record_id TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(record_id) REFERENCES memory_records(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_session_level_time "
                "ON memory_records(session_id, level, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_level_time "
                "ON memory_records(level, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_embedding_status "
                "ON memory_records(embedding_status, level, created_at ASC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model ON memory_embeddings(model)"
            )
            conn.commit()

    @staticmethod
    def _ensure_record_columns(conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_records)").fetchall()}
        if "embedding_status" not in columns:
            conn.execute(
                "ALTER TABLE memory_records ADD COLUMN embedding_status TEXT "
                "NOT NULL DEFAULT 'pending'"
            )
        if "embedding_updated_at" not in columns:
            conn.execute("ALTER TABLE memory_records ADD COLUMN embedding_updated_at TEXT")
        if "embedding_error" not in columns:
            conn.execute("ALTER TABLE memory_records ADD COLUMN embedding_error TEXT")

    def _fetch_pending_records(self, *, limit: int) -> list[sqlite3.Row]:
        if not self._embed_levels:
            return []
        level_values = [level.value for level in self._embed_levels]
        placeholders = ", ".join("?" for _ in level_values)
        sql = (
            "SELECT id, content FROM memory_records "
            "WHERE embedding_status = ? "
            f"AND level IN ({placeholders}) "
            "ORDER BY created_at ASC LIMIT ?"
        )
        params: list[object] = [_EMBEDDING_STATUS_PENDING, *level_values, limit]
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def _count_pending_records(self) -> int:
        if not self._embed_levels:
            return 0
        level_values = [level.value for level in self._embed_levels]
        placeholders = ", ".join("?" for _ in level_values)
        sql = (
            "SELECT COUNT(*) FROM memory_records "
            "WHERE embedding_status = ? "
            f"AND level IN ({placeholders})"
        )
        params: list[object] = [_EMBEDDING_STATUS_PENDING, *level_values]
        with self._connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def _load_embeddings_by_record_ids(
        self,
        record_ids: list[str],
        *,
        model: str,
    ) -> dict[str, dict[int, float]]:
        if not record_ids:
            return {}
        placeholders = ", ".join("?" for _ in record_ids)
        sql = (
            "SELECT record_id, vector_json FROM memory_embeddings "
            f"WHERE model = ? AND record_id IN ({placeholders})"
        )
        params: list[object] = [model, *record_ids]
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return {
            str(row["record_id"]): deserialize_sparse_vector(str(row["vector_json"]))
            for row in rows
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        created_at = datetime.fromisoformat(row["created_at"])
        last_accessed = (
            datetime.fromisoformat(row["last_accessed_at"]) if row["last_accessed_at"] else None
        )
        return MemoryRecord(
            id=row["id"],
            level=MemoryLevel(row["level"]),
            content=row["content"],
            session_id=row["session_id"],
            tags=set(json.loads(row["tags"])),
            salience=float(row["salience"]),
            metadata=json.loads(row["metadata"]),
            created_at=created_at,
            last_accessed_at=last_accessed,
            access_count=int(row["access_count"]),
        )


def create_memory_store(
    *,
    backend: str,
    sqlite_path: str | Path,
    semantic_search_enabled: bool = True,
    lexical_weight: float = 0.45,
    semantic_weight: float = 0.35,
    embedding_provider: str = "hash",
    embedding_model: str = "hash-v1",
    embedding_enabled: bool = True,
    embed_episodic: bool = True,
    embed_semantic: bool = True,
    query_use_embedding_index: bool = True,
    embedding_openai_api_key: str = "",
    embedding_openai_base_url: str = "https://api.openai.com/v1",
    embedding_timeout_sec: float = 20.0,
    embedding_retry_max_attempts: int = 4,
    embedding_retry_base_delay_sec: float = 0.5,
    embedding_retry_max_delay_sec: float = 8.0,
    embedding_retry_jitter: bool = True,
) -> MemoryStore:
    """Factory for selecting memory storage backend."""
    normalized = backend.strip().lower()
    provider_obj: EmbeddingProvider | None = None
    if embedding_enabled:
        provider_obj = create_embedding_provider(
            provider=embedding_provider,
            model=embedding_model,
            openai_api_key=embedding_openai_api_key,
            openai_base_url=embedding_openai_base_url,
            timeout_sec=embedding_timeout_sec,
            openai_retry_max_attempts=embedding_retry_max_attempts,
            openai_retry_base_delay_sec=embedding_retry_base_delay_sec,
            openai_retry_max_delay_sec=embedding_retry_max_delay_sec,
            openai_retry_jitter=embedding_retry_jitter,
        )
    if normalized == "memory":
        return InMemoryMemoryStore(
            semantic_search_enabled=semantic_search_enabled,
            lexical_weight=lexical_weight,
            semantic_weight=semantic_weight,
        )
    if normalized == "sqlite":
        return SQLiteMemoryStore(
            sqlite_path,
            semantic_search_enabled=semantic_search_enabled,
            lexical_weight=lexical_weight,
            semantic_weight=semantic_weight,
            embedding_model=embedding_model,
            embedding_enabled=embedding_enabled,
            embed_episodic=embed_episodic,
            embed_semantic=embed_semantic,
            query_use_embedding_index=query_use_embedding_index,
            embedding_provider=provider_obj,
        )
    raise ValueError(f"Unsupported memory store backend: {backend}")


def score_records(
    *,
    records: list[MemoryRecord],
    session_id: str,
    query: str,
    limit: int,
    now: datetime,
    semantic_scores_by_id: dict[str, float] | None = None,
    semantic_search_enabled: bool = True,
    lexical_weight: float = 0.45,
    semantic_weight: float = 0.35,
) -> list[MemoryMatch]:
    query_tokens = _tokenize(query)
    query_semantic_vec = hash_semantic_vector(query) if semantic_search_enabled else {}
    matches: list[MemoryMatch] = []

    for rec in records:
        score = _score_record(
            rec=rec,
            query_tokens=query_tokens,
            query_semantic_vec=query_semantic_vec,
            now=now,
            session_id=session_id,
            semantic_scores_by_id=semantic_scores_by_id,
            semantic_search_enabled=semantic_search_enabled,
            lexical_weight=lexical_weight,
            semantic_weight=semantic_weight,
        )
        if score <= 0:
            continue
        matches.append(MemoryMatch(record=rec, score=score))

    matches.sort(
        key=lambda m: (m.score, m.record.salience, m.record.created_at),
        reverse=True,
    )
    return matches[:limit]


def _score_record(
    *,
    rec: MemoryRecord,
    query_tokens: set[str],
    query_semantic_vec: dict[int, float],
    now: datetime,
    session_id: str,
    semantic_scores_by_id: dict[str, float] | None,
    semantic_search_enabled: bool,
    lexical_weight: float,
    semantic_weight: float,
) -> float:
    rec_tokens = _tokenize(rec.content)
    overlap = len(query_tokens & rec_tokens)
    lexical = (overlap / max(len(query_tokens), 1)) if query_tokens else 0.0
    semantic = 0.0
    if semantic_scores_by_id is not None and rec.id in semantic_scores_by_id:
        semantic = semantic_scores_by_id[rec.id]
    elif semantic_search_enabled:
        semantic = cosine_sparse(query_semantic_vec, hash_semantic_vector(rec.content))

    # Half-life style decay keeps recent memories easier to retrieve.
    hours = _age_hours(rec.created_at, now)
    recency = math.exp(-hours / (24 * 14))

    session_bonus = 0.1 if rec.session_id == session_id else 0.0
    salience = min(max(rec.salience, 0.0), 1.0)

    retrieval = (lexical_weight * lexical) + (semantic_weight * semantic)

    # If both retrieval signals are zero, still allow salient recent items to surface.
    if retrieval <= 0.0:
        return (salience * 0.1) + (recency * 0.05) + (session_bonus * 0.2)

    return retrieval + (salience * 0.12) + (recency * 0.08) + session_bonus
