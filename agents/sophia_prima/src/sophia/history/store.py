"""Append-only storage for lossless debugging history."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from sophia.history.types import HistoryEventRecord, HistoryEventType


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


class SQLiteHistoryStore:
    """SQLite-backed append-only event log."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def append(self, record: HistoryEventRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO history_events (
                    session_id, run_id, parent_run_id, task_id, turn,
                    event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.run_id,
                    record.parent_run_id,
                    record.task_id,
                    record.turn,
                    record.event_type.value,
                    json.dumps(record.payload),
                    record.created_at.isoformat(),
                ),
            )
            conn.commit()

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
                WHERE {' AND '.join(where)}
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
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> HistoryEventRecord:
        from datetime import datetime

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
