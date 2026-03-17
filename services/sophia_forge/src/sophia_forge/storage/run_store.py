"""SQLite-backed store for forge runs, events, and artifacts."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from sophia_forge_protocol.artifact_models import RunArtifact
from sophia_forge_protocol.event_models import RunEvent
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge_protocol.verification_models import VerificationResult


class ForgeRunStore:
    """Persistence layer for forge runtime state."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS forge_runs (
                    run_id TEXT PRIMARY KEY,
                    client_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    task_text TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    workspace_root TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    error TEXT,
                    changed_files_json TEXT NOT NULL,
                    verification_json TEXT NOT NULL,
                    follow_ups_json TEXT NOT NULL,
                    artifact_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS forge_run_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS forge_run_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    path TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS forge_verification_results (
                    run_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    command TEXT NOT NULL,
                    required INTEGER NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_run(self, request: RunRequest) -> RunResult:
        now = _utc_now()
        run_id = request.run_id or "forge_run"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO forge_runs (
                    run_id, client_name, status, task_text, backend, workspace_root, metadata_json,
                    summary, error, changed_files_json, verification_json, follow_ups_json,
                    artifact_ids_json, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    request.client_name,
                    "queued",
                    request.task,
                    request.backend,
                    request.workspace_root,
                    json.dumps(request.metadata, sort_keys=True),
                    "",
                    None,
                    "[]",
                    "[]",
                    "[]",
                    "[]",
                    now,
                    now,
                    None,
                ),
            )
        return self.get_run(run_id)

    def mark_running(self, run_id: str) -> RunResult:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE forge_runs SET status = ?, updated_at = ? WHERE run_id = ?",
                ("running", now, run_id),
            )
        return self.get_run(run_id)

    def finish_run(self, result: RunResult) -> RunResult:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE forge_runs
                SET status = ?, summary = ?, error = ?, changed_files_json = ?, verification_json = ?,
                    follow_ups_json = ?, artifact_ids_json = ?, updated_at = ?, completed_at = ?
                WHERE run_id = ?
                """,
                (
                    result.status,
                    result.summary,
                    result.error,
                    json.dumps(list(result.changed_files), sort_keys=True),
                    json.dumps(list(result.verification), sort_keys=True),
                    json.dumps(list(result.follow_ups), sort_keys=True),
                    json.dumps(list(result.artifact_ids), sort_keys=True),
                    now,
                    now,
                    result.run_id,
                ),
            )
        return self.get_run(result.run_id or "forge_run")

    def cancel_run(self, run_id: str) -> RunResult:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE forge_runs
                SET status = ?, updated_at = ?, completed_at = ?
                WHERE run_id = ? AND status IN ('queued', 'running')
                """,
                ("cancelled", now, now, run_id),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> RunResult:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, status, summary, error, changed_files_json, verification_json,
                       follow_ups_json, artifact_ids_json
                FROM forge_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunResult(
            run_id=row["run_id"],
            status=row["status"],
            summary=row["summary"] or "",
            error=row["error"],
            changed_files=tuple(json.loads(row["changed_files_json"] or "[]")),
            verification=tuple(json.loads(row["verification_json"] or "[]")),
            follow_ups=tuple(json.loads(row["follow_ups_json"] or "[]")),
            artifact_ids=tuple(json.loads(row["artifact_ids_json"] or "[]")),
        )

    def append_event(self, event: RunEvent) -> RunEvent:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO forge_run_events (
                    run_id, sequence, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.sequence,
                    event.event_type,
                    json.dumps(event.payload, sort_keys=True),
                    event.timestamp,
                ),
            )
        return event

    def list_events(self, run_id: str) -> tuple[RunEvent, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, sequence, event_type, payload_json, created_at
                FROM forge_run_events
                WHERE run_id = ?
                ORDER BY sequence ASC
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            RunEvent(
                run_id=row["run_id"],
                sequence=row["sequence"],
                event_type=row["event_type"],
                timestamp=row["created_at"],
                payload=json.loads(row["payload_json"] or "{}"),
            )
            for row in rows
        )

    def replace_artifacts(self, run_id: str, artifacts: tuple[RunArtifact, ...]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM forge_run_artifacts WHERE run_id = ?", (run_id,))
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO forge_run_artifacts (
                        artifact_id, run_id, artifact_type, content_type, path, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.artifact_id,
                        artifact.run_id,
                        artifact.artifact_type,
                        artifact.content_type,
                        artifact.path,
                        json.dumps(artifact.payload, sort_keys=True) if artifact.payload else None,
                        artifact.created_at,
                    ),
                )

    def list_artifacts(self, run_id: str) -> tuple[RunArtifact, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT artifact_id, run_id, artifact_type, content_type, path, payload_json, created_at
                FROM forge_run_artifacts
                WHERE run_id = ?
                ORDER BY artifact_id ASC
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            RunArtifact(
                artifact_id=row["artifact_id"],
                run_id=row["run_id"],
                artifact_type=row["artifact_type"],
                content_type=row["content_type"],
                path=row["path"],
                payload=json.loads(row["payload_json"]) if row["payload_json"] else None,
                created_at=row["created_at"],
            )
            for row in rows
        )

    def replace_verification_results(
        self,
        run_id: str,
        results: tuple[VerificationResult, ...],
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM forge_verification_results WHERE run_id = ?", (run_id,))
            for result in results:
                conn.execute(
                    """
                    INSERT INTO forge_verification_results (
                        run_id, name, status, command, required, details, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        result.name,
                        result.status,
                        result.command,
                        1 if result.required else 0,
                        result.details,
                        _utc_now(),
                    ),
                )

    def list_verification_results(self, run_id: str) -> tuple[VerificationResult, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name, status, command, required, details
                FROM forge_verification_results
                WHERE run_id = ?
                ORDER BY rowid ASC
                """,
                (run_id,),
            ).fetchall()
        return tuple(
            VerificationResult(
                name=row["name"],
                status=row["status"],
                command=row["command"],
                required=bool(row["required"]),
                details=row["details"],
            )
            for row in rows
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
