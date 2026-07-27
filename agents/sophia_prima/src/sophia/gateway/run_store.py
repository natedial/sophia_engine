"""Persistent storage for gateway runs and structured skill artifacts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sophia.events import AgentEvent


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class GatewayRunStore:
    """SQLite-backed store for run traces and skill artifacts."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def start_run(
        self,
        *,
        run_id: str,
        session_id: str,
        agent_id: str,
        channel: str,
        account_id: str,
        peer_id: str,
        user_id: str | None,
        message_text: str,
    ) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO gateway_runs (
                    run_id, session_id, agent_id, channel, account_id, peer_id,
                    user_id, message_text, status, created_at, updated_at, failure_stage,
                    provider_name, tool_name, service_name, outbound_text_len
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    session_id,
                    agent_id,
                    channel,
                    account_id,
                    peer_id,
                    user_id,
                    message_text,
                    "running",
                    now,
                    now,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            )
            conn.commit()

    def append_event(self, *, run_id: str, sequence: int, event: AgentEvent) -> None:
        now = utc_now_iso()
        payload = serialize_agent_event(event)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_run_events (
                    run_id, sequence, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    sequence,
                    event.type.value,
                    json.dumps(payload),
                    now,
                ),
            )
            conn.execute(
                "UPDATE gateway_runs SET updated_at=? WHERE run_id=?",
                (now, run_id),
            )
            conn.commit()

    def finish_run(
        self,
        *,
        run_id: str,
        status: str,
        final_text: str | None = None,
        error: str | None = None,
        failure_stage: str | None = None,
        provider_name: str | None = None,
        tool_name: str | None = None,
        service_name: str | None = None,
    ) -> None:
        now = utc_now_iso()
        outbound_text_len = len(final_text) if final_text is not None else None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE gateway_runs
                SET status=?, final_text=?, error=?, completed_at=?, updated_at=?,
                    failure_stage=?, provider_name=?, tool_name=?, service_name=?, outbound_text_len=?
                WHERE run_id=?
                """,
                (
                    status,
                    final_text,
                    error,
                    now,
                    now,
                    failure_stage,
                    provider_name,
                    tool_name,
                    service_name,
                    outbound_text_len,
                    run_id,
                ),
            )
            conn.commit()

    def update_run_diagnostics(
        self,
        *,
        run_id: str,
        failure_stage: str | None = None,
        provider_name: str | None = None,
        tool_name: str | None = None,
        service_name: str | None = None,
        outbound_text_len: int | None = None,
    ) -> None:
        """Update correlated diagnostic fields without completing the run."""
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE gateway_runs
                SET updated_at=?,
                    failure_stage=COALESCE(?, failure_stage),
                    provider_name=COALESCE(?, provider_name),
                    tool_name=COALESCE(?, tool_name),
                    service_name=COALESCE(?, service_name),
                    outbound_text_len=COALESCE(?, outbound_text_len)
                WHERE run_id=?
                """,
                (
                    now,
                    failure_stage,
                    provider_name,
                    tool_name,
                    service_name,
                    outbound_text_len,
                    run_id,
                ),
            )
            conn.commit()

    def save_skill_artifact(
        self,
        *,
        skill_name: str,
        run_id: str | None,
        session_id: str | None,
        agent_id: str,
        payload: dict[str, Any],
    ) -> str:
        artifact_id = f"artifact_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_skill_artifacts (
                    artifact_id, skill_name, run_id, session_id, agent_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    skill_name,
                    run_id,
                    session_id,
                    agent_id,
                    json.dumps(sanitize_for_json(payload)),
                    now,
                ),
            )
            conn.commit()
        return artifact_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, session_id, agent_id, channel, account_id, peer_id, user_id,
                       message_text, status, final_text, error, created_at, updated_at, completed_at,
                       failure_stage, provider_name, tool_name, service_name, outbound_text_len
                FROM gateway_runs
                WHERE run_id=?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            event_rows = conn.execute(
                """
                SELECT sequence, event_type, payload_json, created_at
                FROM gateway_run_events
                WHERE run_id=?
                ORDER BY sequence ASC
                """,
                (run_id,),
            ).fetchall()
            acquisition_rows = conn.execute(
                """
                SELECT job_id, run_id, session_id, agent_id, playbook_id, indicator_family,
                       requested_source, mode, rationale, retention_target, status,
                       created_at, updated_at
                FROM gateway_acquisition_jobs
                WHERE run_id=?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
            acquisition_artifact_rows = conn.execute(
                """
                SELECT artifact_id, job_id, run_id, session_id, agent_id, stage, status,
                       payload_json, created_at
                FROM gateway_acquisition_artifacts
                WHERE run_id=?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()
            skill_artifact_rows = conn.execute(
                """
                SELECT artifact_id, skill_name, run_id, session_id, agent_id, payload_json, created_at
                FROM gateway_skill_artifacts
                WHERE run_id=?
                ORDER BY created_at ASC
                """,
                (run_id,),
            ).fetchall()

        return {
            "run_id": row["run_id"],
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "channel": row["channel"],
            "account_id": row["account_id"],
            "peer_id": row["peer_id"],
            "user_id": row["user_id"],
            "message_text": row["message_text"],
            "status": row["status"],
            "final_text": row["final_text"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
            "failure_stage": row["failure_stage"],
            "provider_name": row["provider_name"],
            "tool_name": row["tool_name"],
            "service_name": row["service_name"],
            "outbound_text_len": row["outbound_text_len"],
            "events": [
                {
                    "sequence": event_row["sequence"],
                    "event_type": event_row["event_type"],
                    "payload": json.loads(event_row["payload_json"]),
                    "created_at": event_row["created_at"],
                }
                for event_row in event_rows
            ],
            "skill_artifacts": [
                {
                    "artifact_id": artifact_row["artifact_id"],
                    "skill_name": artifact_row["skill_name"],
                    "run_id": artifact_row["run_id"],
                    "session_id": artifact_row["session_id"],
                    "agent_id": artifact_row["agent_id"],
                    "payload": json.loads(artifact_row["payload_json"]),
                    "created_at": artifact_row["created_at"],
                }
                for artifact_row in skill_artifact_rows
            ],
            "acquisition_jobs": [
                {
                    "job_id": job_row["job_id"],
                    "run_id": job_row["run_id"],
                    "session_id": job_row["session_id"],
                    "agent_id": job_row["agent_id"],
                    "playbook_id": job_row["playbook_id"],
                    "indicator_family": job_row["indicator_family"],
                    "requested_source": job_row["requested_source"],
                    "mode": job_row["mode"],
                    "rationale": job_row["rationale"],
                    "retention_target": job_row["retention_target"],
                    "status": job_row["status"],
                    "created_at": job_row["created_at"],
                    "updated_at": job_row["updated_at"],
                }
                for job_row in acquisition_rows
            ],
            "acquisition_artifacts": [
                {
                    "artifact_id": artifact_row["artifact_id"],
                    "job_id": artifact_row["job_id"],
                    "run_id": artifact_row["run_id"],
                    "session_id": artifact_row["session_id"],
                    "agent_id": artifact_row["agent_id"],
                    "stage": artifact_row["stage"],
                    "status": artifact_row["status"],
                    "payload": json.loads(artifact_row["payload_json"]),
                    "created_at": artifact_row["created_at"],
                }
                for artifact_row in acquisition_artifact_rows
            ],
        }

    def list_runs(
        self,
        *,
        limit: int = 25,
        agent_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id:
            clauses.append("agent_id=?")
            params.append(agent_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT run_id, session_id, agent_id, channel, account_id, peer_id, user_id,
                       message_text, status, final_text, error, created_at, updated_at, completed_at,
                       failure_stage, provider_name, tool_name, service_name, outbound_text_len,
                       (
                           SELECT COUNT(*)
                           FROM gateway_run_events
                           WHERE gateway_run_events.run_id = gateway_runs.run_id
                       ) AS event_count,
                       (
                           SELECT COUNT(*)
                           FROM gateway_skill_artifacts
                           WHERE gateway_skill_artifacts.run_id = gateway_runs.run_id
                       ) AS skill_artifact_count
                FROM gateway_runs
                {where_sql}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [
            {
                "run_id": row["run_id"],
                "session_id": row["session_id"],
                "agent_id": row["agent_id"],
                "channel": row["channel"],
                "account_id": row["account_id"],
                "peer_id": row["peer_id"],
                "user_id": row["user_id"],
                "message_text": row["message_text"],
                "status": row["status"],
                "final_text": row["final_text"],
                "error": row["error"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
                "failure_stage": row["failure_stage"],
                "provider_name": row["provider_name"],
                "tool_name": row["tool_name"],
                "service_name": row["service_name"],
                "outbound_text_len": row["outbound_text_len"],
                "event_count": row["event_count"],
                "skill_artifact_count": row["skill_artifact_count"],
            }
            for row in rows
        ]

    def get_skill_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT artifact_id, skill_name, run_id, session_id, agent_id, payload_json, created_at
                FROM gateway_skill_artifacts
                WHERE artifact_id=?
                """,
                (artifact_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "artifact_id": row["artifact_id"],
            "skill_name": row["skill_name"],
            "run_id": row["run_id"],
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    def create_acquisition_job(
        self,
        *,
        run_id: str | None,
        session_id: str,
        agent_id: str,
        playbook_id: str | None,
        indicator_family: str,
        requested_source: str | None,
        mode: str,
        rationale: str,
        retention_target: str,
        status: str = "queued",
    ) -> dict[str, Any]:
        job_id = f"acq_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_acquisition_jobs (
                    job_id, run_id, session_id, agent_id, playbook_id, indicator_family,
                    requested_source, mode, rationale, retention_target, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    run_id,
                    session_id,
                    agent_id,
                    playbook_id,
                    indicator_family,
                    requested_source,
                    mode,
                    rationale,
                    retention_target,
                    status,
                    now,
                    now,
                ),
            )
            conn.commit()
        return self.get_acquisition_job(job_id) or {}

    def get_acquisition_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT job_id, run_id, session_id, agent_id, playbook_id, indicator_family,
                       requested_source, mode, rationale, retention_target, status,
                       created_at, updated_at
                FROM gateway_acquisition_jobs
                WHERE job_id=?
                """,
                (job_id,),
            ).fetchone()
            artifact_rows = conn.execute(
                """
                SELECT artifact_id, job_id, run_id, session_id, agent_id, stage, status,
                       payload_json, created_at
                FROM gateway_acquisition_artifacts
                WHERE job_id=?
                ORDER BY created_at ASC
                """,
                (job_id,),
            ).fetchall()
        if row is None:
            return None
        return {
            "job_id": row["job_id"],
            "run_id": row["run_id"],
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "playbook_id": row["playbook_id"],
            "indicator_family": row["indicator_family"],
            "requested_source": row["requested_source"],
            "mode": row["mode"],
            "rationale": row["rationale"],
            "retention_target": row["retention_target"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "artifacts": [
                {
                    "artifact_id": artifact_row["artifact_id"],
                    "job_id": artifact_row["job_id"],
                    "run_id": artifact_row["run_id"],
                    "session_id": artifact_row["session_id"],
                    "agent_id": artifact_row["agent_id"],
                    "stage": artifact_row["stage"],
                    "status": artifact_row["status"],
                    "payload": json.loads(artifact_row["payload_json"]),
                    "created_at": artifact_row["created_at"],
                }
                for artifact_row in artifact_rows
            ],
        }

    def update_acquisition_job_status(self, *, job_id: str, status: str) -> dict[str, Any] | None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE gateway_acquisition_jobs
                SET status=?, updated_at=?
                WHERE job_id=?
                """,
                (status, now, job_id),
            )
            conn.commit()
        return self.get_acquisition_job(job_id)

    def save_acquisition_artifact(
        self,
        *,
        job_id: str,
        run_id: str | None,
        session_id: str,
        agent_id: str,
        stage: str,
        status: str,
        payload: dict[str, Any],
    ) -> str:
        artifact_id = f"acqart_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_acquisition_artifacts (
                    artifact_id, job_id, run_id, session_id, agent_id, stage, status,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    job_id,
                    run_id,
                    session_id,
                    agent_id,
                    stage,
                    status,
                    json.dumps(sanitize_for_json(payload)),
                    now,
                ),
            )
            conn.commit()
        return artifact_id

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS gateway_runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    peer_id TEXT NOT NULL,
                    user_id TEXT,
                    message_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    final_text TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    failure_stage TEXT,
                    provider_name TEXT,
                    tool_name TEXT,
                    service_name TEXT,
                    outbound_text_len INTEGER
                );

                CREATE TABLE IF NOT EXISTS gateway_run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_gateway_run_events_run_seq
                ON gateway_run_events (run_id, sequence);

                CREATE TABLE IF NOT EXISTS gateway_skill_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    run_id TEXT,
                    session_id TEXT,
                    agent_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gateway_acquisition_jobs (
                    job_id TEXT PRIMARY KEY,
                    run_id TEXT,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    playbook_id TEXT,
                    indicator_family TEXT NOT NULL,
                    requested_source TEXT,
                    mode TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    retention_target TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gateway_acquisition_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    run_id TEXT,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(gateway_runs)").fetchall()
            }
            if "failure_stage" not in columns:
                conn.execute("ALTER TABLE gateway_runs ADD COLUMN failure_stage TEXT")
            if "provider_name" not in columns:
                conn.execute("ALTER TABLE gateway_runs ADD COLUMN provider_name TEXT")
            if "tool_name" not in columns:
                conn.execute("ALTER TABLE gateway_runs ADD COLUMN tool_name TEXT")
            if "service_name" not in columns:
                conn.execute("ALTER TABLE gateway_runs ADD COLUMN service_name TEXT")
            if "outbound_text_len" not in columns:
                conn.execute("ALTER TABLE gateway_runs ADD COLUMN outbound_text_len INTEGER")
            conn.commit()


def serialize_agent_event(event: AgentEvent) -> dict[str, Any]:
    """Convert AgentEvent to JSON-safe payload."""
    return {
        "type": event.type.value,
        "data": sanitize_for_json(event.data),
    }


def sanitize_for_json(value: Any) -> Any:
    """Recursively convert complex objects to JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): sanitize_for_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_json(item) for item in value]
    if is_dataclass(value):
        payload: dict[str, Any] = {}
        for field in fields(value):
            if field.name.startswith("_"):
                continue
            payload[field.name] = sanitize_for_json(getattr(value, field.name))
        return payload
    return str(value)
