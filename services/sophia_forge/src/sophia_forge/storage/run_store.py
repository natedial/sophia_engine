"""SQLite-backed store for forge runs, events, and artifacts."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from sophia_forge.evals.models import EvalRunSummary
from sophia_forge_protocol.artifact_models import RunArtifact
from sophia_forge_protocol.event_models import RunEvent
from sophia_forge.core.outcomes import classify_failure
from sophia_forge_protocol.run_models import (
    CapabilityHandoff,
    ControlMessage,
    FailureClassCount,
    RunCheckpoint,
    RunMetricsSummary,
    RunRequest,
    RunResult,
    RunSession,
    TaskTypeMetrics,
)
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
                    request_json TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS forge_run_sessions (
                    session_id TEXT PRIMARY KEY,
                    client_name TEXT NOT NULL,
                    task_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latest_run_id TEXT,
                    latest_checkpoint_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS forge_run_session_runs (
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, run_id)
                );

                CREATE TABLE IF NOT EXISTS forge_control_messages (
                    control_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT,
                    control_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    applied_at TEXT
                );

                CREATE TABLE IF NOT EXISTS forge_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    summary_artifact_id TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS forge_eval_runs (
                    eval_run_id TEXT PRIMARY KEY,
                    corpus_name TEXT NOT NULL,
                    backend_override TEXT,
                    artifact_id TEXT NOT NULL,
                    summary_path TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS forge_capability_handoffs (
                    tool_name TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            _ensure_column(
                conn,
                table_name="forge_runs",
                column_name="request_json",
                column_sql="TEXT NOT NULL DEFAULT '{}'",
            )
            _ensure_column(
                conn,
                table_name="forge_run_sessions",
                column_name="latest_checkpoint_id",
                column_sql="TEXT",
            )

    def create_run(self, request: RunRequest) -> RunResult:
        now = _utc_now()
        run_id = request.run_id or "forge_run"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO forge_runs (
                    run_id, client_name, status, task_text, backend, workspace_root, request_json, metadata_json,
                    summary, error, changed_files_json, verification_json, follow_ups_json,
                    artifact_ids_json, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    request.client_name,
                    "queued",
                    request.task,
                    request.backend,
                    request.workspace_root,
                    json.dumps(request.model_dump(mode="json"), sort_keys=True),
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

    def create_session(
        self,
        *,
        session_id: str,
        client_name: str,
        task: str,
        metadata: dict[str, object] | None = None,
    ) -> RunSession:
        now = _utc_now()
        payload = metadata or {}
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO forge_run_sessions (
                    session_id, client_name, task_text, status, latest_run_id, latest_checkpoint_id,
                    metadata_json, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    client_name,
                    task,
                    "active",
                    None,
                    None,
                    json.dumps(payload, sort_keys=True),
                    now,
                    now,
                    None,
                ),
            )
        return self.get_session(session_id)

    def session_exists(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM forge_run_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row is not None

    def get_session(self, session_id: str) -> RunSession:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, client_name, task_text, status, latest_run_id, metadata_json,
                       latest_checkpoint_id, created_at, updated_at, completed_at
                FROM forge_run_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            run_rows = conn.execute(
                """
                SELECT run_id
                FROM forge_run_session_runs
                WHERE session_id = ?
                ORDER BY ordinal ASC
                """,
                (session_id,),
            ).fetchall()
        if row is None:
            raise KeyError(session_id)
        return RunSession(
            session_id=row["session_id"],
            client_name=row["client_name"],
            task=row["task_text"],
            status=row["status"],
            latest_run_id=row["latest_run_id"],
            latest_checkpoint_id=row["latest_checkpoint_id"],
            run_ids=tuple(run_row["run_id"] for run_row in run_rows),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def bind_run_to_session(self, *, session_id: str, run_id: str) -> None:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(ordinal), 0) AS max_ordinal
                FROM forge_run_session_runs
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            ordinal = int(row["max_ordinal"] or 0) + 1 if row is not None else 1
            conn.execute(
                """
                INSERT OR REPLACE INTO forge_run_session_runs (
                    session_id, run_id, ordinal, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (session_id, run_id, ordinal, now),
            )
            conn.execute(
                """
                UPDATE forge_run_sessions
                SET status = ?, latest_run_id = ?, updated_at = ?, completed_at = ?
                WHERE session_id = ?
                """,
                ("active", run_id, now, None, session_id),
            )

    def list_session_runs(self, session_id: str) -> tuple[RunResult, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.run_id
                FROM forge_run_session_runs s
                JOIN forge_runs r ON r.run_id = s.run_id
                WHERE s.session_id = ?
                ORDER BY s.ordinal ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(self.get_run(row["run_id"]) for row in rows)

    def create_control_message(
        self,
        *,
        control_id: str,
        session_id: str,
        run_id: str | None,
        control_type: str,
        message: str,
        metadata: dict[str, object] | None = None,
    ) -> ControlMessage:
        now = _utc_now()
        payload = metadata or {}
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forge_control_messages (
                    control_id, session_id, run_id, control_type, status, message,
                    metadata_json, created_at, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    control_id,
                    session_id,
                    run_id,
                    control_type,
                    "queued",
                    message,
                    json.dumps(payload, sort_keys=True),
                    now,
                    None,
                ),
            )
            conn.execute(
                """
                UPDATE forge_run_sessions
                SET status = ?, updated_at = ?, completed_at = ?
                WHERE session_id = ?
                """,
                ("active", now, None, session_id),
            )
        return self.get_control_message(control_id)

    def get_control_message(self, control_id: str) -> ControlMessage:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT control_id, session_id, run_id, control_type, status, message,
                       metadata_json, created_at, applied_at
                FROM forge_control_messages
                WHERE control_id = ?
                """,
                (control_id,),
            ).fetchone()
        if row is None:
            raise KeyError(control_id)
        return ControlMessage(
            control_id=row["control_id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            control_type=row["control_type"],
            status=row["status"],
            message=row["message"],
            created_at=row["created_at"],
            applied_at=row["applied_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def list_control_messages(
        self,
        session_id: str,
        *,
        status: str | None = None,
    ) -> tuple[ControlMessage, ...]:
        with self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    """
                    SELECT control_id
                    FROM forge_control_messages
                    WHERE session_id = ?
                    ORDER BY created_at ASC
                    """,
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT control_id
                    FROM forge_control_messages
                    WHERE session_id = ? AND status = ?
                    ORDER BY created_at ASC
                    """,
                    (session_id, status),
                ).fetchall()
        return tuple(self.get_control_message(row["control_id"]) for row in rows)

    def mark_control_messages_applied(
        self,
        *,
        control_ids: tuple[str, ...],
        run_id: str,
    ) -> tuple[ControlMessage, ...]:
        if not control_ids:
            return ()
        now = _utc_now()
        with self._lock, self._connect() as conn:
            for control_id in control_ids:
                conn.execute(
                    """
                    UPDATE forge_control_messages
                    SET status = ?, run_id = ?, applied_at = ?
                    WHERE control_id = ?
                    """,
                    ("applied", run_id, now, control_id),
                )
        return tuple(self.get_control_message(control_id) for control_id in control_ids)

    def create_checkpoint(
        self,
        *,
        checkpoint_id: str,
        session_id: str,
        run_id: str,
        summary_artifact_id: str,
        summary: str,
        metadata: dict[str, object] | None = None,
    ) -> RunCheckpoint:
        now = _utc_now()
        payload = metadata or {}
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO forge_checkpoints (
                    checkpoint_id, session_id, run_id, summary_artifact_id,
                    summary_text, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    session_id,
                    run_id,
                    summary_artifact_id,
                    summary,
                    json.dumps(payload, sort_keys=True),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE forge_run_sessions
                SET latest_checkpoint_id = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (checkpoint_id, now, session_id),
            )
        return self.get_checkpoint(checkpoint_id)

    def get_checkpoint(self, checkpoint_id: str) -> RunCheckpoint:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT checkpoint_id, session_id, run_id, summary_artifact_id,
                       summary_text, metadata_json, created_at
                FROM forge_checkpoints
                WHERE checkpoint_id = ?
                """,
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            raise KeyError(checkpoint_id)
        return RunCheckpoint(
            checkpoint_id=row["checkpoint_id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            summary_artifact_id=row["summary_artifact_id"],
            summary=row["summary_text"],
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def list_checkpoints(self, session_id: str) -> tuple[RunCheckpoint, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT checkpoint_id
                FROM forge_checkpoints
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(self.get_checkpoint(row["checkpoint_id"]) for row in rows)

    def update_session_from_run(self, *, session_id: str, run_id: str, run_status: str) -> None:
        now = _utc_now()
        session_status = "active" if run_status in {"queued", "running"} else run_status
        completed_at = None if session_status == "active" else now
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE forge_run_sessions
                SET status = ?, latest_run_id = ?, updated_at = ?, completed_at = ?
                WHERE session_id = ?
                """,
                (session_status, run_id, now, completed_at, session_id),
            )

    def get_run_request(self, run_id: str) -> RunRequest:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT request_json
                FROM forge_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunRequest.model_validate(json.loads(row["request_json"]))

    def mark_running(self, run_id: str) -> RunResult:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE forge_runs SET status = ?, updated_at = ? WHERE run_id = ?",
                ("running", now, run_id),
            )
        return self.get_run(run_id)

    def update_run_metadata(self, run_id: str, updates: dict[str, object]) -> None:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT metadata_json
                FROM forge_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata.update(updates)
            conn.execute(
                """
                UPDATE forge_runs
                SET metadata_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (json.dumps(metadata, sort_keys=True), now, run_id),
            )

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

    def list_runs(
        self,
        *,
        limit: int = 25,
        status: str | None = None,
    ) -> tuple[dict[str, object], ...]:
        params: list[object] = []
        where_sql = ""
        if status is not None:
            where_sql = "WHERE status = ?"
            params.append(status)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT run_id, client_name, status, task_text, backend, workspace_root,
                       request_json, summary, error, artifact_ids_json, created_at, updated_at, completed_at
                FROM forge_runs
                {where_sql}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return tuple(
            {
                "run_id": row["run_id"],
                "client_name": row["client_name"],
                "status": row["status"],
                "task": row["task_text"],
                "backend": row["backend"],
                "workspace_root": row["workspace_root"],
                "summary": row["summary"] or "",
                "error": row["error"],
                "artifact_ids": tuple(json.loads(row["artifact_ids_json"] or "[]")),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
                "promotion_mode": _extract_promotion_mode(row["request_json"]),
            }
            for row in rows
        )

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

    def list_events(self, run_id: str, *, after_sequence: int | None = None) -> tuple[RunEvent, ...]:
        with self._connect() as conn:
            if after_sequence is None:
                rows = conn.execute(
                    """
                    SELECT run_id, sequence, event_type, payload_json, created_at
                    FROM forge_run_events
                    WHERE run_id = ?
                    ORDER BY sequence ASC
                    """,
                    (run_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT run_id, sequence, event_type, payload_json, created_at
                    FROM forge_run_events
                    WHERE run_id = ? AND sequence > ?
                    ORDER BY sequence ASC
                    """,
                    (run_id, after_sequence),
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

    def summarize_metrics(self) -> RunMetricsSummary:
        with self._connect() as conn:
            run_rows = conn.execute(
                """
                SELECT run_id, status, error, metadata_json
                FROM forge_runs
                ORDER BY created_at ASC
                """
            ).fetchall()
            verification_rows = conn.execute(
                """
                SELECT run_id, status, required
                FROM forge_verification_results
                ORDER BY created_at ASC
                """
            ).fetchall()

        total_runs = len(run_rows)
        completed_runs = 0
        failed_runs = 0
        retry_runs = 0
        failure_counts: dict[str, int] = {}
        task_type_totals: dict[str, int] = {}
        task_type_completed: dict[str, int] = {}

        for row in run_rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            status = row["status"]
            error = row["error"]
            task_type = str(metadata.get("task_type") or "unspecified").strip() or "unspecified"
            task_type_totals[task_type] = task_type_totals.get(task_type, 0) + 1
            if status == "completed":
                completed_runs += 1
                task_type_completed[task_type] = task_type_completed.get(task_type, 0) + 1
            elif status not in {"queued", "running"}:
                failed_runs += 1
                failure_class = classify_failure(status=status, error=error)
                failure_counts[failure_class] = failure_counts.get(failure_class, 0) + 1

            if metadata.get("retry_of_run_id") or int(metadata.get("attempt", 1) or 1) > 1:
                retry_runs += 1

        verification_by_run: dict[str, list[tuple[str, bool]]] = {}
        for row in verification_rows:
            verification_by_run.setdefault(row["run_id"], []).append(
                (row["status"], bool(row["required"]))
            )

        runs_with_verification = len(verification_by_run)
        verification_passed = 0
        for run_id, results in verification_by_run.items():
            required_failures = [
                status for status, required in results if required and status != "passed"
            ]
            if not required_failures:
                verification_passed += 1

        task_types = tuple(
            TaskTypeMetrics(
                task_type=task_type,
                total_runs=task_type_totals[task_type],
                completed_runs=task_type_completed.get(task_type, 0),
            )
            for task_type in sorted(task_type_totals)
        )
        common_failure_classes = tuple(
            FailureClassCount(failure_class=name, count=count)
            for name, count in sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))
        )
        return RunMetricsSummary(
            total_runs=total_runs,
            completed_runs=completed_runs,
            failed_runs=failed_runs,
            success_rate=(completed_runs / total_runs) if total_runs else 0.0,
            retry_rate=(retry_runs / total_runs) if total_runs else 0.0,
            runs_with_verification=runs_with_verification,
            verification_pass_rate=(
                verification_passed / runs_with_verification if runs_with_verification else None
            ),
            common_failure_classes=common_failure_classes,
            task_types=task_types,
        )

    def save_eval_run(self, summary: EvalRunSummary) -> EvalRunSummary:
        if summary.eval_run_id is None or summary.artifact_id is None or summary.summary_path is None:
            raise ValueError("EvalRunSummary must include eval_run_id, artifact_id, and summary_path")
        created_at = summary.created_at or _utc_now()
        persisted = summary.model_copy(update={"created_at": created_at})
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO forge_eval_runs (
                    eval_run_id, corpus_name, backend_override, artifact_id, summary_path, summary_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persisted.eval_run_id,
                    persisted.corpus_name,
                    persisted.backend_override,
                    persisted.artifact_id,
                    persisted.summary_path,
                    json.dumps(persisted.model_dump(mode="json"), sort_keys=True),
                    created_at,
                ),
            )
        return persisted

    def get_eval_run(self, eval_run_id: str) -> EvalRunSummary:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT summary_json
                FROM forge_eval_runs
                WHERE eval_run_id = ?
                """,
                (eval_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(eval_run_id)
        return EvalRunSummary.model_validate(json.loads(row["summary_json"]))

    def list_eval_runs(self) -> tuple[EvalRunSummary, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT summary_json
                FROM forge_eval_runs
                ORDER BY created_at DESC
                """
            ).fetchall()
        return tuple(EvalRunSummary.model_validate(json.loads(row["summary_json"])) for row in rows)

    def upsert_capability_handoffs(
        self,
        entries: tuple[CapabilityHandoff, ...],
    ) -> tuple[CapabilityHandoff, ...]:
        if not entries:
            return ()
        now = _utc_now()
        persisted: list[CapabilityHandoff] = []
        with self._lock, self._connect() as conn:
            for entry in entries:
                record = entry.model_copy(update={"updated_at": entry.updated_at or now})
                conn.execute(
                    """
                    INSERT OR REPLACE INTO forge_capability_handoffs (
                        tool_name, payload_json, updated_at
                    ) VALUES (?, ?, ?)
                    """,
                    (
                        record.tool_name,
                        json.dumps(record.model_dump(mode="json"), sort_keys=True),
                        record.updated_at,
                    ),
                )
                persisted.append(record)
        return tuple(persisted)

    def list_capability_handoffs(self) -> tuple[CapabilityHandoff, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM forge_capability_handoffs
                ORDER BY tool_name ASC
                """
            ).fetchall()
        return tuple(
            CapabilityHandoff.model_validate(json.loads(row["payload_json"]))
            for row in rows
        )

    def list_active_run_ids(self) -> tuple[str, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id
                FROM forge_runs
                WHERE status IN ('queued', 'running')
                ORDER BY created_at ASC
                """
            ).fetchall()
        return tuple(row["run_id"] for row in rows)

    def list_terminal_run_ids_before(self, cutoff: datetime) -> tuple[str, ...]:
        cutoff_text = cutoff.isoformat().replace("+00:00", "Z")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id
                FROM forge_runs
                WHERE status NOT IN ('queued', 'running')
                  AND COALESCE(completed_at, updated_at, created_at) < ?
                ORDER BY COALESCE(completed_at, updated_at, created_at) ASC
                """,
                (cutoff_text,),
            ).fetchall()
        return tuple(row["run_id"] for row in rows)

    def list_eval_run_ids_before(self, cutoff: datetime) -> tuple[str, ...]:
        cutoff_text = cutoff.isoformat().replace("+00:00", "Z")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT eval_run_id
                FROM forge_eval_runs
                WHERE created_at < ?
                ORDER BY created_at ASC
                """,
                (cutoff_text,),
            ).fetchall()
        return tuple(row["eval_run_id"] for row in rows)

    def prune_run_artifacts(self, run_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM forge_run_artifacts WHERE run_id = ?", (run_id,))
            conn.execute(
                "UPDATE forge_runs SET artifact_ids_json = ?, updated_at = ? WHERE run_id = ?",
                ("[]", _utc_now(), run_id),
            )

    def prune_eval_artifact(self, eval_run_id: str) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT summary_json
                FROM forge_eval_runs
                WHERE eval_run_id = ?
                """,
                (eval_run_id,),
            ).fetchone()
            if row is None:
                return
            summary_json = json.loads(row["summary_json"] or "{}")
            summary_json["artifact_id"] = ""
            summary_json["summary_path"] = ""
            conn.execute(
                """
                UPDATE forge_eval_runs
                SET artifact_id = ?, summary_path = ?, summary_json = ?
                WHERE eval_run_id = ?
                """,
                ("", "", json.dumps(summary_json, sort_keys=True), eval_run_id),
            )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _extract_promotion_mode(request_json: str | None) -> str | None:
    if not request_json:
        return None
    try:
        payload = json.loads(request_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    promotion_policy = payload.get("promotion_policy")
    if not isinstance(promotion_policy, dict):
        return None
    mode = promotion_policy.get("mode")
    return str(mode) if mode else None


def _ensure_column(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name in columns:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
