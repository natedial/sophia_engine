"""SQLite-backed storage for Sophia Sentry."""

import json
import sqlite3
from pathlib import Path

from .types import WatchDefinition, WatchEvent, WatchRuntimeState


class SentryStore:
    """Persistent storage for watches, state, and events."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sentry_watches (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sentry_state (
                    watch_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sentry_events (
                    id TEXT PRIMARY KEY,
                    watch_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def reset(self) -> None:
        """Clear persisted state for tests."""
        with self._connect() as conn:
            conn.execute("DELETE FROM sentry_events")
            conn.execute("DELETE FROM sentry_state")
            conn.execute("DELETE FROM sentry_watches")
            conn.commit()

    def upsert_watch(self, watch: WatchDefinition) -> WatchDefinition:
        """Insert or update a watch definition."""
        payload = watch.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sentry_watches (id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (watch.id, json.dumps(payload), payload["updated_at"]),
            )
            conn.commit()
        return watch

    def get_watch(self, watch_id: str) -> WatchDefinition | None:
        """Load one watch definition."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sentry_watches WHERE id = ?",
                (watch_id,),
            ).fetchone()
        if row is None:
            return None
        return WatchDefinition.model_validate_json(row["payload_json"])

    def list_watches(self) -> list[WatchDefinition]:
        """List registered watch definitions."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM sentry_watches ORDER BY id"
            ).fetchall()
        return [WatchDefinition.model_validate_json(row["payload_json"]) for row in rows]

    def upsert_state(self, state: WatchRuntimeState) -> WatchRuntimeState:
        """Insert or update runtime state for one watch."""
        payload = state.model_dump(mode="json")
        updated_at = payload.get("last_evaluated_at") or payload.get("last_triggered_at")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sentry_state (watch_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(watch_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (state.watch_id, json.dumps(payload), str(updated_at or "")),
            )
            conn.commit()
        return state

    def get_state(self, watch_id: str) -> WatchRuntimeState | None:
        """Load runtime state for one watch."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM sentry_state WHERE watch_id = ?",
                (watch_id,),
            ).fetchone()
        if row is None:
            return None
        return WatchRuntimeState.model_validate_json(row["state_json"])

    def create_event(self, event: WatchEvent) -> WatchEvent:
        """Persist a new watch event."""
        payload = event.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sentry_events (id, watch_id, created_at, severity, summary, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.watch_id,
                    payload["created_at"],
                    event.severity.value,
                    event.summary,
                    json.dumps(payload),
                ),
            )
            conn.commit()
        return event

    def list_events(self, watch_id: str | None = None) -> list[WatchEvent]:
        """List persisted events, optionally scoped to one watch."""
        with self._connect() as conn:
            if watch_id:
                rows = conn.execute(
                    """
                    SELECT payload_json
                    FROM sentry_events
                    WHERE watch_id = ?
                    ORDER BY created_at DESC, id DESC
                    """,
                    (watch_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT payload_json
                    FROM sentry_events
                    ORDER BY created_at DESC, id DESC
                    """
                ).fetchall()
        return [WatchEvent.model_validate_json(row["payload_json"]) for row in rows]
