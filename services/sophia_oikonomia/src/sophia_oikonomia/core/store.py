"""SQLite-backed store for Oikonomia state."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .types import (
    ModelDefinition,
    ModelState,
    ModelRun,
    PromotionReview,
    PublicationState,
    PublishedProjection,
)


class OikonomiaStore:
    """Persistence layer for models, reviews, runs, and publications."""

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

    def reset(self) -> None:
        """Clear all stored state. Test-only helper."""
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                DELETE FROM oikonomia_models;
                DELETE FROM oikonomia_reviews;
                DELETE FROM oikonomia_runs;
                DELETE FROM oikonomia_publications;
                """
            )

    def save_model(self, definition: ModelDefinition) -> ModelDefinition:
        payload = definition.model_dump(mode="json")
        with self._lock, self._connect() as conn:
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
        with self._lock, self._connect() as conn:
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
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO oikonomia_runs (
                    run_id, model_id, status, created_at, completed_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.model_id,
                    run.status.value,
                    run.created_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                    json.dumps(run.model_dump(mode="json"), sort_keys=True),
                ),
            )
        return run

    def get_run(self, run_id: str) -> ModelRun | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM oikonomia_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return ModelRun.model_validate(json.loads(row["payload_json"]))

    def list_runs(self) -> list[ModelRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM oikonomia_runs
                ORDER BY created_at
                """
            ).fetchall()
        return [
            ModelRun.model_validate(json.loads(row["payload_json"]))
            for row in rows
        ]

    def save_publication(self, publication: PublishedProjection) -> PublishedProjection:
        current = self.get_latest_publication(publication.model_id)
        with self._lock, self._connect() as conn:
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
