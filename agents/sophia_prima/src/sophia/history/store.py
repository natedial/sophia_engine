"""Append-only storage for lossless debugging history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Protocol

from sophia.history.types import HistoryEventRecord, HistoryEventType, SessionSearchResult


class HistoryStore(Protocol):
    """Interface for lossless history storage."""

    def append(self, record: HistoryEventRecord) -> None:
        """Persist one history event."""

    def list_events(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        limit: int = 200,
        newest_first: bool = False,
    ) -> list[HistoryEventRecord]:
        """List events for a session/run slice."""

    def search_sessions(
        self,
        *,
        query: str,
        exclude_session_ids: set[str] | None = None,
        max_sessions: int = 3,
        max_hits: int = 20,
        max_results_per_session: int = 5,
    ) -> list[SessionSearchResult]:
        """Search past sessions via FTS5, return grouped excerpts."""


class SQLiteHistoryStore:
    """SQLite-backed append-only event log."""

    def __init__(self, db_path: str | Path, backfill_on_init: bool = True) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        if backfill_on_init:
            self._backfill_search_text()

    def append(self, record: HistoryEventRecord) -> None:
        search_text, display_text = self._extract_searchable_text(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO history_events (
                    session_id, run_id, parent_run_id, task_id, turn,
                    event_type, payload_json, search_text, display_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.run_id,
                    record.parent_run_id,
                    record.task_id,
                    record.turn,
                    record.event_type.value,
                    json.dumps(record.payload),
                    search_text,
                    display_text,
                    record.created_at.isoformat(),
                ),
            )
            conn.commit()

    def _extract_searchable_text(self, record: HistoryEventRecord) -> tuple[str | None, str | None]:
        if record.event_type == HistoryEventType.TURN_INPUT:
            text = record.payload.get("user_message", "")
            return (text, text)
        elif record.event_type == HistoryEventType.TURN_OUTPUT:
            text = record.payload.get("assistant_message", "")
            return (text, text)
        return (None, None)

    def list_events(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        limit: int = 200,
        newest_first: bool = False,
    ) -> list[HistoryEventRecord]:
        order = "DESC" if newest_first else "ASC"
        params: list[object] = [session_id]
        where = ["session_id = ?"]
        if run_id is not None:
            where.append("run_id = ?")
            params.append(run_id)
        params.append(max(1, limit))

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT session_id, run_id, parent_run_id, task_id, turn,
                       event_type, payload_json, created_at
                FROM history_events
                WHERE {" AND ".join(where)}
                ORDER BY created_at {order}, id {order}
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    parent_run_id TEXT,
                    task_id TEXT,
                    turn INTEGER,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    search_text TEXT,
                    display_text TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_session_time "
                "ON history_events(session_id, created_at ASC, id ASC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_run_time "
                "ON history_events(run_id, created_at ASC, id ASC)"
            )
            self._ensure_search_columns(conn)
            self._ensure_fts_index(conn)
            conn.commit()

    def _ensure_search_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(history_events)").fetchall()}
        if "search_text" not in columns:
            conn.execute("ALTER TABLE history_events ADD COLUMN search_text TEXT")
        if "display_text" not in columns:
            conn.execute("ALTER TABLE history_events ADD COLUMN display_text TEXT")

    def _ensure_fts_index(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5("
            "search_text, content='history_events', content_rowid='id')"
        )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS history_fts_insert AFTER INSERT ON history_events BEGIN
                INSERT INTO history_fts(rowid, search_text)
                VALUES (new.id, new.search_text);
            END
            """
        )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS history_fts_delete AFTER DELETE ON history_events BEGIN
                INSERT INTO history_fts(history_fts, rowid, search_text)
                VALUES ('delete', old.id, old.search_text);
            END
            """
        )

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS history_fts_update AFTER UPDATE ON history_events BEGIN
                INSERT INTO history_fts(history_fts, rowid, search_text)
                VALUES ('delete', old.id, old.search_text);
                INSERT INTO history_fts(rowid, search_text)
                VALUES (new.id, new.search_text);
            END
            """
        )

    def _backfill_search_text(self) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, event_type, payload_json FROM history_events WHERE search_text IS NULL"
            ).fetchall()

            for row in rows:
                event_type = str(row["event_type"])
                payload = json.loads(str(row["payload_json"]))
                search_text = None
                display_text = None

                if event_type == "turn_input":
                    search_text = payload.get("user_message", "")
                    display_text = search_text
                elif event_type == "turn_output":
                    search_text = payload.get("assistant_message", "")
                    display_text = search_text

                if search_text:
                    conn.execute(
                        "UPDATE history_events SET search_text = ?, display_text = ? WHERE id = ?",
                        (search_text, display_text, row["id"]),
                    )

            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> HistoryEventRecord:
        return HistoryEventRecord(
            session_id=str(row["session_id"]),
            run_id=row["run_id"],
            parent_run_id=row["parent_run_id"],
            task_id=row["task_id"],
            turn=int(row["turn"]) if row["turn"] is not None else None,
            event_type=HistoryEventType(str(row["event_type"])),
            payload=json.loads(str(row["payload_json"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def search_sessions(
        self,
        *,
        query: str,
        exclude_session_ids: set[str] | None = None,
        max_sessions: int = 3,
        max_hits: int = 20,
        max_results_per_session: int = 5,
    ) -> list[SessionSearchResult]:
        """Search past sessions via FTS5, return grouped excerpts."""
        exclude = exclude_session_ids or set()
        if not query.strip():
            return []

        fts_query = " OR ".join(query.strip().split())
        where = ["history_fts MATCH ?"]
        params: list[object] = [fts_query]

        if exclude:
            placeholders = ", ".join("?" for _ in exclude)
            where.append(f"h.session_id NOT IN ({placeholders})")
            params.extend(sorted(exclude))

        params.append(max_hits)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT h.id, h.session_id, h.created_at, h.event_type, h.payload_json
                FROM history_events h
                JOIN history_fts fts ON h.id = fts.rowid
                WHERE {' AND '.join(where)}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()

        if not rows:
            return []

        session_groups: dict[str, list[dict]] = {}
        for row in rows:
            session_id = str(row["session_id"])
            if session_id not in session_groups:
                session_groups[session_id] = []
            session_groups[session_id].append(
                {
                    "created_at": datetime.fromisoformat(str(row["created_at"])),
                    "event_type": str(row["event_type"]),
                    "payload": json.loads(str(row["payload_json"])),
                }
            )

        results: list[SessionSearchResult] = []
        sorted_sessions = sorted(
            session_groups.items(),
            key=lambda x: max(e["created_at"] for e in x[1]),
            reverse=True,
        )

        for session_id, events in sorted_sessions[:max_sessions]:
            excerpts: list[str] = []
            for event in events[:max_results_per_session]:
                excerpt = self._extract_searchable_excerpt(event)
                if excerpt:
                    excerpts.append(excerpt)

            if not excerpts:
                continue

            earliest = min(e["created_at"] for e in events)
            latest = max(e["created_at"] for e in events)

            results.append(
                SessionSearchResult(
                    session_id=session_id,
                    earliest=earliest,
                    latest=latest,
                    excerpts=excerpts,
                    match_count=len(events),
                )
            )

        return results

    def _extract_searchable_excerpt(self, event: dict) -> str | None:
        event_type = event.get("event_type")
        payload = event.get("payload", {})

        if event_type == "turn_input":
            return payload.get("user_message")
        elif event_type == "turn_output":
            return payload.get("assistant_message")
        return None
