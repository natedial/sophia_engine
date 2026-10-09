"""SQLite-backed store for Oikonomia state."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator

from .clock import Clock, SystemClock
from .types import (
    ClaimKind,
    ClaimOutcome,
    FinishKind,
    FinishOutcome,
    ModelDefinition,
    ModelRun,
    ModelState,
    PromotionReview,
    PublicationState,
    PublishedProjection,
    RunStatus,
    TERMINAL_RUN_STATUSES,
)


class OikonomiaStore:
    """Persistence layer for models, reviews, runs, and publications."""

    def __init__(self, db_path: Path, *, clock: Clock | None = None) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock: Clock = clock or SystemClock()
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.isolation_level = None
        return conn

    @contextmanager
    def _immediate(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS oikonomia_models (
                    model_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    production_slot TEXT,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS oikonomia_reviews (
                    review_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    requested_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS oikonomia_runs (
                    run_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS oikonomia_publications (
                    publication_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(oikonomia_runs)").fetchall()
            }
            if "fingerprint" not in columns:
                conn.execute("ALTER TABLE oikonomia_runs ADD COLUMN fingerprint TEXT")
            if "lease_owner" not in columns:
                conn.execute("ALTER TABLE oikonomia_runs ADD COLUMN lease_owner TEXT")
            if "lease_generation" not in columns:
                conn.execute(
                    "ALTER TABLE oikonomia_runs ADD COLUMN lease_generation "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "lease_expires_at" not in columns:
                conn.execute(
                    "ALTER TABLE oikonomia_runs ADD COLUMN lease_expires_at TEXT"
                )
            if "heartbeat_at" not in columns:
                conn.execute("ALTER TABLE oikonomia_runs ADD COLUMN heartbeat_at TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_oikonomia_runs_fingerprint "
                "ON oikonomia_runs(fingerprint) "
                "WHERE fingerprint IS NOT NULL AND fingerprint != ''"
            )

    def reset(self) -> None:
        """Clear all stored state. Test-only helper."""
        with self._lock, self._immediate() as conn:
            conn.execute("DELETE FROM oikonomia_models")
            conn.execute("DELETE FROM oikonomia_reviews")
            conn.execute("DELETE FROM oikonomia_runs")
            conn.execute("DELETE FROM oikonomia_publications")

    def save_model(self, definition: ModelDefinition) -> ModelDefinition:
        payload = definition.model_dump(mode="json")
        with self._lock, self._immediate() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO oikonomia_models (
                    model_id, state, production_slot, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    definition.id,
                    definition.state.value,
                    definition.production_slot,
                    definition.updated_at.isoformat(),
                    json.dumps(payload, sort_keys=True),
                ),
            )
        return definition

    def get_model(self, model_id: str) -> ModelDefinition | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM oikonomia_models
                WHERE model_id = ?
                """,
                (model_id,),
            ).fetchone()
        if row is None:
            return None
        return ModelDefinition.model_validate(json.loads(row["payload_json"]))

    def list_models(self) -> list[ModelDefinition]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM oikonomia_models
                ORDER BY model_id
                """
            ).fetchall()
        return [
            ModelDefinition.model_validate(json.loads(row["payload_json"]))
            for row in rows
        ]

    def save_review(self, review: PromotionReview) -> PromotionReview:
        with self._lock, self._immediate() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO oikonomia_reviews (
                    review_id, model_id, requested_state, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    review.id,
                    review.model_id,
                    review.requested_state.value,
                    review.created_at.isoformat(),
                    json.dumps(review.model_dump(mode="json"), sort_keys=True),
                ),
            )
        return review

    def list_reviews(self, model_id: str | None = None) -> list[PromotionReview]:
        query = """
            SELECT payload_json
            FROM oikonomia_reviews
        """
        args: tuple[object, ...] = ()
        if model_id is not None:
            query += " WHERE model_id = ?"
            args = (model_id,)
        query += " ORDER BY created_at"

        with self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [
            PromotionReview.model_validate(json.loads(row["payload_json"]))
            for row in rows
        ]

    def get_latest_review(self, model_id: str) -> PromotionReview | None:
        reviews = self.list_reviews(model_id)
        return reviews[-1] if reviews else None

    def save_run(self, run: ModelRun) -> ModelRun:
        """Insert a new queued run. Existing rows are not overwritten."""
        return self.insert_run(run)

    def insert_run(self, run: ModelRun) -> ModelRun:
        """Create a queued run. Fingerprint conflicts return the existing row."""
        with self._lock, self._immediate() as conn:
            return self._insert_run_conn(conn, run)

    def _insert_run_conn(self, conn: sqlite3.Connection, run: ModelRun) -> ModelRun:
        existing = self._get_run_conn(conn, run.id)
        if existing is not None:
            return existing
        if run.fingerprint:
            found = self._get_run_by_fingerprint_conn(conn, run.fingerprint)
            if found is not None:
                return found
        try:
            self._write_run(conn, run, insert=True)
        except sqlite3.IntegrityError:
            found = self._get_run_by_fingerprint_conn(conn, run.fingerprint or "")
            if found is None:
                raise
            return found
        return run

    def claim_run(
        self,
        run_id: str,
        owner: str,
        lease_duration: timedelta,
    ) -> ClaimOutcome:
        with self._lock, self._immediate() as conn:
            run = self._get_run_conn(conn, run_id)
            if run is None:
                raise ValueError(f"Unknown run: {run_id}")
            now = self.clock.now()
            if run.status in TERMINAL_RUN_STATUSES:
                return ClaimOutcome(kind=ClaimKind.TERMINAL, run=run)
            if run.status == RunStatus.RUNNING:
                if not run.lease_owner or run.lease_expires_at is None:
                    return ClaimOutcome(kind=ClaimKind.UNCLAIMABLE, run=run)
                if run.lease_expires_at > now:
                    return ClaimOutcome(kind=ClaimKind.PENDING, run=run)
                generation = run.lease_generation + 1
                acquired = _with_lease(run, owner, generation, now, lease_duration)
                cursor = conn.execute(
                    """
                    UPDATE oikonomia_runs
                    SET status = ?, lease_owner = ?, lease_generation = ?,
                        lease_expires_at = ?, heartbeat_at = ?, payload_json = ?
                    WHERE run_id = ? AND status = ? AND lease_generation = ?
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= ?
                    """,
                    (
                        acquired.status.value,
                        acquired.lease_owner,
                        acquired.lease_generation,
                        _iso(acquired.lease_expires_at),
                        _iso(acquired.heartbeat_at),
                        _payload(acquired),
                        run_id,
                        RunStatus.RUNNING.value,
                        run.lease_generation,
                        _iso(now),
                    ),
                )
                if cursor.rowcount != 1:
                    current = self._get_run_conn(conn, run_id)
                    assert current is not None
                    return self._classify_claim(current, now)
                return ClaimOutcome(kind=ClaimKind.ACQUIRED, run=acquired)
            if run.status != RunStatus.QUEUED:
                return ClaimOutcome(kind=ClaimKind.UNCLAIMABLE, run=run)
            generation = run.lease_generation + 1
            acquired = _with_lease(run, owner, generation, now, lease_duration)
            cursor = conn.execute(
                """
                UPDATE oikonomia_runs
                SET status = ?, lease_owner = ?, lease_generation = ?,
                    lease_expires_at = ?, heartbeat_at = ?, payload_json = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    acquired.status.value,
                    acquired.lease_owner,
                    acquired.lease_generation,
                    _iso(acquired.lease_expires_at),
                    _iso(acquired.heartbeat_at),
                    _payload(acquired),
                    run_id,
                    RunStatus.QUEUED.value,
                ),
            )
            if cursor.rowcount != 1:
                current = self._get_run_conn(conn, run_id)
                assert current is not None
                return self._classify_claim(current, now)
            return ClaimOutcome(kind=ClaimKind.ACQUIRED, run=acquired)

    def _classify_claim(self, run: ModelRun, now) -> ClaimOutcome:
        if run.status in TERMINAL_RUN_STATUSES:
            return ClaimOutcome(kind=ClaimKind.TERMINAL, run=run)
        if run.status == RunStatus.RUNNING:
            if not run.lease_owner or run.lease_expires_at is None:
                return ClaimOutcome(kind=ClaimKind.UNCLAIMABLE, run=run)
            if run.lease_expires_at > now:
                return ClaimOutcome(kind=ClaimKind.PENDING, run=run)
        if run.status == RunStatus.QUEUED:
            return ClaimOutcome(kind=ClaimKind.PENDING, run=run)
        return ClaimOutcome(kind=ClaimKind.UNCLAIMABLE, run=run)

    def renew_lease(
        self,
        run_id: str,
        owner: str,
        generation: int,
        lease_duration: timedelta,
    ) -> bool:
        with self._lock, self._immediate() as conn:
            now = self.clock.now()
            run = self._get_run_conn(conn, run_id)
            if run is None:
                return False
            if (
                run.status != RunStatus.RUNNING
                or run.lease_owner != owner
                or run.lease_generation != generation
                or run.lease_expires_at is None
                or run.lease_expires_at <= now
            ):
                return False
            renewed = run.model_copy(
                update={
                    "lease_expires_at": now + lease_duration,
                    "heartbeat_at": now,
                }
            )
            cursor = conn.execute(
                """
                UPDATE oikonomia_runs
                SET lease_expires_at = ?, heartbeat_at = ?, payload_json = ?
                WHERE run_id = ? AND status = ? AND lease_owner = ?
                  AND lease_generation = ? AND lease_expires_at IS NOT NULL
                  AND lease_expires_at > ?
                """,
                (
                    _iso(renewed.lease_expires_at),
                    _iso(renewed.heartbeat_at),
                    _payload(renewed),
                    run_id,
                    RunStatus.RUNNING.value,
                    owner,
                    generation,
                    _iso(now),
                ),
            )
            return cursor.rowcount == 1

    def finish_run(
        self,
        run_id: str,
        owner: str,
        generation: int,
        result: ModelRun,
    ) -> FinishOutcome:
        if result.status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            raise ValueError("Run completion must end in succeeded or failed status")
        with self._lock, self._immediate() as conn:
            current = self._get_run_conn(conn, run_id)
            if current is None:
                raise ValueError(f"Unknown run: {run_id}")
            if current.status in TERMINAL_RUN_STATUSES:
                return FinishOutcome(kind=FinishKind.ALREADY_TERMINAL, run=current)
            now = self.clock.now()
            if (
                current.status != RunStatus.RUNNING
                or current.lease_owner != owner
                or current.lease_generation != generation
                or current.lease_expires_at is None
                or current.lease_expires_at <= now
            ):
                return FinishOutcome(kind=FinishKind.REJECTED, run=current)
            finished = result.model_copy(
                update={
                    "id": current.id,
                    "model_id": current.model_id,
                    "status": result.status,
                    "completed_at": now,
                    "lease_owner": None,
                    "lease_generation": current.lease_generation,
                    "lease_expires_at": None,
                    "heartbeat_at": None,
                }
            )
            cursor = conn.execute(
                """
                UPDATE oikonomia_runs
                SET status = ?, completed_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL,
                    payload_json = ?
                WHERE run_id = ? AND status = ? AND lease_owner = ?
                  AND lease_generation = ? AND lease_expires_at IS NOT NULL
                  AND lease_expires_at > ?
                """,
                (
                    finished.status.value,
                    _iso(finished.completed_at),
                    _payload(finished),
                    run_id,
                    RunStatus.RUNNING.value,
                    owner,
                    generation,
                    _iso(now),
                ),
            )
            if cursor.rowcount != 1:
                latest = self._get_run_conn(conn, run_id)
                assert latest is not None
                if latest.status in TERMINAL_RUN_STATUSES:
                    return FinishOutcome(kind=FinishKind.ALREADY_TERMINAL, run=latest)
                return FinishOutcome(kind=FinishKind.REJECTED, run=latest)
            return FinishOutcome(kind=FinishKind.ACCEPTED, run=finished)

    def mark_published(self, run_id: str) -> ModelRun:
        with self._lock, self._immediate() as conn:
            run = self._get_run_conn(conn, run_id)
            if run is None:
                raise ValueError(f"Unknown run: {run_id}")
            if run.status == RunStatus.PUBLISHED:
                return run
            if run.status != RunStatus.SUCCEEDED:
                raise ValueError("Only successful runs can be published")
            published = run.model_copy(update={"status": RunStatus.PUBLISHED})
            cursor = conn.execute(
                """
                UPDATE oikonomia_runs
                SET status = ?, payload_json = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    RunStatus.PUBLISHED.value,
                    _payload(published),
                    run_id,
                    RunStatus.SUCCEEDED.value,
                ),
            )
            if cursor.rowcount != 1:
                latest = self._get_run_conn(conn, run_id)
                assert latest is not None
                if latest.status == RunStatus.PUBLISHED:
                    return latest
                raise ValueError("Only successful runs can be published")
            return published

    def recover_legacy_run(
        self,
        run_id: str,
        owner: str,
        lease_duration: timedelta,
        *,
        expire_immediately: bool = True,
    ) -> ModelRun:
        """Attach lease metadata to a pre-migration RUNNING row.

        Missing lease fields do not prove the worker is dead. Call this only
        after old workers have been stopped. By default the attached lease is
        already expired so a later claim_run can acquire the next generation.
        """
        with self._lock, self._immediate() as conn:
            run = self._get_run_conn(conn, run_id)
            if run is None:
                raise ValueError(f"Unknown run: {run_id}")
            if run.status != RunStatus.RUNNING or run.lease_owner is not None:
                raise ValueError(
                    f"Run {run_id} is not a legacy RUNNING row without lease metadata"
                )
            now = self.clock.now()
            expires = now if expire_immediately else now + lease_duration
            generation = run.lease_generation + 1
            recovered = run.model_copy(
                update={
                    "lease_owner": owner,
                    "lease_generation": generation,
                    "lease_expires_at": expires,
                    "heartbeat_at": now,
                }
            )
            cursor = conn.execute(
                """
                UPDATE oikonomia_runs
                SET lease_owner = ?, lease_generation = ?,
                    lease_expires_at = ?, heartbeat_at = ?, payload_json = ?
                WHERE run_id = ? AND status = ? AND lease_owner IS NULL
                """,
                (
                    recovered.lease_owner,
                    recovered.lease_generation,
                    _iso(recovered.lease_expires_at),
                    _iso(recovered.heartbeat_at),
                    _payload(recovered),
                    run_id,
                    RunStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"Run {run_id} is not a legacy RUNNING row without lease metadata"
                )
            return recovered

    def get_run_by_fingerprint(self, fingerprint: str) -> ModelRun | None:
        if not fingerprint:
            return None
        with self._connect() as conn:
            return self._get_run_by_fingerprint_conn(conn, fingerprint)

    def _get_run_by_fingerprint_conn(
        self, conn: sqlite3.Connection, fingerprint: str
    ) -> ModelRun | None:
        if not fingerprint:
            return None
        row = conn.execute(
            """
            SELECT run_id, model_id, status, created_at, completed_at,
                   fingerprint, lease_owner, lease_generation, lease_expires_at,
                   heartbeat_at, payload_json
            FROM oikonomia_runs
            WHERE fingerprint = ?
            """,
            (fingerprint,),
        ).fetchone()
        if row is None:
            return None
        return _run_from_row(row)

    def get_run(self, run_id: str) -> ModelRun | None:
        with self._connect() as conn:
            return self._get_run_conn(conn, run_id)

    def _get_run_conn(self, conn: sqlite3.Connection, run_id: str) -> ModelRun | None:
        row = conn.execute(
            """
            SELECT run_id, model_id, status, created_at, completed_at,
                   fingerprint, lease_owner, lease_generation, lease_expires_at,
                   heartbeat_at, payload_json
            FROM oikonomia_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return _run_from_row(row)

    def list_runs(self) -> list[ModelRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, model_id, status, created_at, completed_at,
                       fingerprint, lease_owner, lease_generation,
                       lease_expires_at, heartbeat_at, payload_json
                FROM oikonomia_runs
                ORDER BY created_at
                """
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def _write_run(
        self, conn: sqlite3.Connection, run: ModelRun, *, insert: bool
    ) -> None:
        args = (
            run.id,
            run.model_id,
            run.status.value,
            run.created_at.isoformat(),
            run.completed_at.isoformat() if run.completed_at else None,
            run.fingerprint,
            run.lease_owner,
            run.lease_generation,
            _iso(run.lease_expires_at),
            _iso(run.heartbeat_at),
            _payload(run),
        )
        if insert:
            conn.execute(
                """
                INSERT INTO oikonomia_runs (
                    run_id, model_id, status, created_at, completed_at,
                    fingerprint, lease_owner, lease_generation,
                    lease_expires_at, heartbeat_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                args,
            )
            return
        conn.execute(
            """
            UPDATE oikonomia_runs SET
                model_id = ?, status = ?, created_at = ?, completed_at = ?,
                fingerprint = ?, lease_owner = ?, lease_generation = ?,
                lease_expires_at = ?, heartbeat_at = ?, payload_json = ?
            WHERE run_id = ?
            """,
            args[1:] + (run.id,),
        )

    def save_publication(self, publication: PublishedProjection) -> PublishedProjection:
        current = self.get_latest_publication(publication.model_id)
        with self._lock, self._immediate() as conn:
            if current is not None:
                superseded = current.model_copy(update={"state": PublicationState.SUPERSEDED})
                conn.execute(
                    """
                    INSERT OR REPLACE INTO oikonomia_publications (
                        publication_id, model_id, run_id, state, published_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        superseded.id,
                        superseded.model_id,
                        superseded.run_id,
                        superseded.state.value,
                        superseded.published_at.isoformat(),
                        json.dumps(superseded.model_dump(mode="json"), sort_keys=True),
                    ),
                )

            conn.execute(
                """
                INSERT OR REPLACE INTO oikonomia_publications (
                    publication_id, model_id, run_id, state, published_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    publication.id,
                    publication.model_id,
                    publication.run_id,
                    publication.state.value,
                    publication.published_at.isoformat(),
                    json.dumps(publication.model_dump(mode="json"), sort_keys=True),
                ),
            )
        return publication

    def list_publications(self) -> list[PublishedProjection]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM oikonomia_publications
                ORDER BY published_at
                """
            ).fetchall()
        return [
            PublishedProjection.model_validate(json.loads(row["payload_json"]))
            for row in rows
        ]

    def get_latest_publication(self, model_id: str) -> PublishedProjection | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM oikonomia_publications
                WHERE model_id = ?
                ORDER BY published_at DESC
                LIMIT 1
                """,
                (model_id,),
            ).fetchone()
        if row is None:
            return None
        return PublishedProjection.model_validate(json.loads(row["payload_json"]))

    def get_current_champion(self, production_slot: str) -> ModelDefinition | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM oikonomia_models
                WHERE production_slot = ? AND state = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (production_slot, ModelState.CHAMPION.value),
            ).fetchone()
        if row is None:
            return None
        return ModelDefinition.model_validate(json.loads(row["payload_json"]))

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            models = conn.execute("SELECT COUNT(*) AS count FROM oikonomia_models").fetchone()
            runs = conn.execute("SELECT COUNT(*) AS count FROM oikonomia_runs").fetchone()
            reviews = conn.execute("SELECT COUNT(*) AS count FROM oikonomia_reviews").fetchone()
            publications = conn.execute(
                "SELECT COUNT(*) AS count FROM oikonomia_publications"
            ).fetchone()
        return {
            "models": int(models["count"]) if models else 0,
            "runs": int(runs["count"]) if runs else 0,
            "reviews": int(reviews["count"]) if reviews else 0,
            "publications": int(publications["count"]) if publications else 0,
        }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _payload(run: ModelRun) -> str:
    return json.dumps(run.model_dump(mode="json"), sort_keys=True)


def _run_from_row(row: sqlite3.Row) -> ModelRun:
    payload = json.loads(row["payload_json"])
    payload["status"] = row["status"]
    payload["fingerprint"] = row["fingerprint"] or payload.get("fingerprint")
    payload["lease_owner"] = row["lease_owner"]
    payload["lease_generation"] = int(row["lease_generation"] or 0)
    payload["lease_expires_at"] = row["lease_expires_at"]
    payload["heartbeat_at"] = row["heartbeat_at"]
    return ModelRun.model_validate(payload)


def _with_lease(
    run: ModelRun,
    owner: str,
    generation: int,
    now,
    lease_duration: timedelta,
) -> ModelRun:
    return run.model_copy(
        update={
            "status": RunStatus.RUNNING,
            "started_at": run.started_at or now,
            "error": None,
            "lease_owner": owner,
            "lease_generation": generation,
            "lease_expires_at": now + lease_duration,
            "heartbeat_at": now,
        }
    )


__all__ = ["OikonomiaStore"]
