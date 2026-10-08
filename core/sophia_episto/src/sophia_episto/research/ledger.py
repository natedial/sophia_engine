"""SQLite research-case ledger.

Evidence acceptance and the resulting assessment revision are written in one
transaction. Contribution IDs, idempotency keys, and run fingerprints are unique.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from sophia_episto.research.contracts import (
    AgentProposal,
    EmpiricalResult,
    ResultStatus,
    EvidenceAssessment,
    HypothesisAssessment,
    MechanismHypothesis,
    ResearchCase,
    VariableSpec,
)
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode


class ResearchLedger:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS variables (
                    variable_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hypotheses (
                    hypothesis_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    cause_id TEXT NOT NULL,
                    effect_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contributions (
                    contribution_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    independence_group TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS results (
                    run_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    vintage TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assessments (
                    hypothesis_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assessment_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hypothesis_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    case_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    PRIMARY KEY (case_id, idempotency_key)
                );
                """
            )

    def get_idempotent(
        self, case_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT response_json FROM idempotency "
                "WHERE case_id = ? AND idempotency_key = ?",
                (case_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["response_json"])

    def put_idempotent(
        self,
        conn: sqlite3.Connection,
        case_id: str,
        idempotency_key: str,
        operation: str,
        response: dict[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO idempotency "
            "(case_id, idempotency_key, operation, response_json) "
            "VALUES (?, ?, ?, ?)",
            (case_id, idempotency_key, operation, json.dumps(response)),
        )

    def save_case(self, case: ResearchCase) -> None:
        payload = case.model_dump(mode="json")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO cases (case_id, revision, payload_json) VALUES (?, ?, ?) "
                "ON CONFLICT(case_id) DO UPDATE SET revision = excluded.revision, "
                "payload_json = excluded.payload_json",
                (case.case_id, case.revision, json.dumps(payload)),
            )

    def get_case(self, case_id: str) -> ResearchCase | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        if row is None:
            return None
        return ResearchCase.model_validate_json(row["payload_json"])

    def require_case(self, case_id: str) -> ResearchCase:
        case = self.get_case(case_id)
        if case is None:
            raise ProtocolError(
                ProtocolErrorCode.NOT_FOUND,
                f"Unknown case: {case_id}",
            )
        return case

    def require_revision(self, case: ResearchCase, expected_revision: int) -> None:
        if case.revision != expected_revision:
            raise ProtocolError(
                ProtocolErrorCode.STALE_REVISION,
                "Stale case revision",
                details={
                    "expected_revision": expected_revision,
                    "current_revision": case.revision,
                },
            )

    def bump_case(self, conn: sqlite3.Connection, case: ResearchCase) -> ResearchCase:
        updated = case.model_copy(
            update={"revision": case.revision + 1, "updated_at": case.updated_at}
        )
        conn.execute(
            "UPDATE cases SET revision = ?, payload_json = ? WHERE case_id = ?",
            (updated.revision, updated.model_dump_json(), updated.case_id),
        )
        return updated

    def save_variable(self, variable: VariableSpec) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO variables (variable_id, payload_json) VALUES (?, ?) "
                "ON CONFLICT(variable_id) DO UPDATE SET payload_json = excluded.payload_json",
                (variable.variable_id, variable.model_dump_json()),
            )

    def get_variable(self, variable_id: str) -> VariableSpec | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM variables WHERE variable_id = ?",
                (variable_id,),
            ).fetchone()
        if row is None:
            return None
        return VariableSpec.model_validate_json(row["payload_json"])

    def save_hypothesis(self, hypothesis: MechanismHypothesis) -> None:
        with self._lock, self._connect() as conn:
            self._upsert_hypothesis(conn, hypothesis)

    def _upsert_hypothesis(
        self, conn: sqlite3.Connection, hypothesis: MechanismHypothesis
    ) -> None:
        conn.execute(
            "INSERT INTO hypotheses "
            "(hypothesis_id, case_id, revision, cause_id, effect_id, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(hypothesis_id) DO UPDATE SET revision = excluded.revision, "
            "payload_json = excluded.payload_json",
            (
                hypothesis.hypothesis_id,
                hypothesis.case_id,
                hypothesis.revision,
                hypothesis.cause_variable_id,
                hypothesis.effect_variable_id,
                hypothesis.model_dump_json(),
            ),
        )

    def get_hypothesis(self, hypothesis_id: str) -> MechanismHypothesis | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM hypotheses WHERE hypothesis_id = ?",
                (hypothesis_id,),
            ).fetchone()
        if row is None:
            return None
        return MechanismHypothesis.model_validate_json(row["payload_json"])

    def list_hypotheses(self, case_id: str) -> list[MechanismHypothesis]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM hypotheses WHERE case_id = ?",
                (case_id,),
            ).fetchall()
        return [MechanismHypothesis.model_validate_json(row["payload_json"]) for row in rows]

    def get_contribution(self, contribution_id: str) -> EvidenceAssessment | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM contributions WHERE contribution_id = ?",
                (contribution_id,),
            ).fetchone()
        if row is None:
            return None
        return EvidenceAssessment.model_validate_json(row["payload_json"])

    def list_contributions(self, case_id: str) -> list[EvidenceAssessment]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM contributions WHERE case_id = ?",
                (case_id,),
            ).fetchall()
        return [EvidenceAssessment.model_validate_json(row["payload_json"]) for row in rows]

    def get_result(self, run_id: str) -> EmpiricalResult | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM results WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return EmpiricalResult.model_validate_json(row["payload_json"])

    def get_result_by_fingerprint(self, fingerprint: str) -> EmpiricalResult | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM results WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row is None:
            return None
        return EmpiricalResult.model_validate_json(row["payload_json"])

    def list_results(self, case_id: str) -> list[EmpiricalResult]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM results WHERE case_id = ?",
                (case_id,),
            ).fetchall()
        return [EmpiricalResult.model_validate_json(row["payload_json"]) for row in rows]

    def get_assessment(self, hypothesis_id: str) -> HypothesisAssessment | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM assessments WHERE hypothesis_id = ?",
                (hypothesis_id,),
            ).fetchone()
        if row is None:
            return None
        return HypothesisAssessment.model_validate_json(row["payload_json"])

    def list_assessments(self, case_id: str) -> list[HypothesisAssessment]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM assessments WHERE case_id = ?",
                (case_id,),
            ).fetchall()
        return [HypothesisAssessment.model_validate_json(row["payload_json"]) for row in rows]

    def list_assessment_history(self, hypothesis_id: str) -> list[HypothesisAssessment]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM assessment_history "
                "WHERE hypothesis_id = ? ORDER BY revision",
                (hypothesis_id,),
            ).fetchall()
        return [HypothesisAssessment.model_validate_json(row["payload_json"]) for row in rows]

    def list_proposals(self, case_id: str) -> list[AgentProposal]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM proposals WHERE case_id = ?",
                (case_id,),
            ).fetchall()
        return [AgentProposal.model_validate_json(row["payload_json"]) for row in rows]

    def transact_evidence(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        new_contributions: list[EvidenceAssessment],
        existing_ids: list[str],
        independence_groups: list[str],
    ) -> dict[str, Any]:
        """Insert new contributions and bump the case revision atomically."""
        with self._lock, self._connect() as conn:
            if new_contributions:
                case = self._bump(conn, case)
                for item in new_contributions:
                    conn.execute(
                        "INSERT INTO contributions "
                        "(contribution_id, case_id, independence_group, payload_json) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            item.contribution_id,
                            item.case_id,
                            item.independence_group,
                            item.model_dump_json(),
                        ),
                    )
            response = {
                "case_id": case.case_id,
                "revision": case.revision,
                "contribution_ids": existing_ids
                + [item.contribution_id for item in new_contributions],
                "independence_groups": sorted(set(independence_groups)),
                "created_contribution_ids": [
                    item.contribution_id for item in new_contributions
                ],
                "provenance": [
                    {
                        "contribution_id": item.contribution_id,
                        "status": item.provenance_status.value,
                    }
                    for item in new_contributions
                ]
                + [
                    {
                        "contribution_id": contribution_id,
                        "status": "duplicate",
                    }
                    for contribution_id in existing_ids
                ],
            }
            self.put_idempotent(
                conn, case.case_id, idempotency_key, "submit_evidence", response
            )
            return response

    def transact_hypothesis(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        hypothesis: MechanismHypothesis,
        assessment: HypothesisAssessment,
        variables: list[VariableSpec],
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            case = self._bump(conn, case)
            for variable in variables:
                conn.execute(
                    "INSERT INTO variables (variable_id, payload_json) VALUES (?, ?) "
                    "ON CONFLICT(variable_id) DO UPDATE SET "
                    "payload_json = excluded.payload_json",
                    (variable.variable_id, variable.model_dump_json()),
                )
            self._upsert_hypothesis(conn, hypothesis)
            self._write_assessment(conn, assessment)
            response = {
                "case_id": case.case_id,
                "revision": case.revision,
                "hypothesis": hypothesis.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            }
            self.put_idempotent(
                conn, case.case_id, idempotency_key, "propose_hypothesis", response
            )
            return response

    def transact_queued_result(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        result: EmpiricalResult,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT payload_json FROM results WHERE fingerprint = ?",
                (result.fingerprint,),
            ).fetchone()
            if existing is not None:
                loaded = EmpiricalResult.model_validate_json(existing["payload_json"])
                response = {
                    "case_id": case.case_id,
                    "revision": case.revision,
                    "result": loaded.model_dump(mode="json"),
                    "replayed": True,
                }
                self.put_idempotent(
                    conn, case.case_id, idempotency_key, "request_test", response
                )
                return response
            case = self._bump(conn, case)
            try:
                conn.execute(
                    "INSERT INTO results "
                    "(run_id, case_id, fingerprint, vintage, payload_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        result.run_id,
                        result.case_id,
                        result.fingerprint,
                        result.input_snapshot.vintage,
                        result.model_dump_json(),
                    ),
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT payload_json FROM results WHERE fingerprint = ?",
                    (result.fingerprint,),
                ).fetchone()
                loaded = EmpiricalResult.model_validate_json(row["payload_json"])
                response = {
                    "case_id": case.case_id,
                    "revision": case.revision,
                    "result": loaded.model_dump(mode="json"),
                    "replayed": True,
                }
                self.put_idempotent(
                    conn, case.case_id, idempotency_key, "request_test", response
                )
                return response
            response = {
                "case_id": case.case_id,
                "revision": case.revision,
                "result": result.model_dump(mode="json"),
            }
            self.put_idempotent(
                conn, case.case_id, idempotency_key, "request_test", response
            )
            return response

    def claim_queued_run(self, result: EmpiricalResult) -> bool:
        """Atomically move a queued run to running. False if another client claimed it."""
        running = result.model_copy(update={"status": ResultStatus.RUNNING})
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM results WHERE run_id = ?",
                (result.run_id,),
            ).fetchone()
            if row is None:
                return False
            current = EmpiricalResult.model_validate_json(row["payload_json"])
            if current.status != ResultStatus.QUEUED:
                return False
            conn.execute(
                "UPDATE results SET payload_json = ? WHERE run_id = ?",
                (running.model_dump_json(), result.run_id),
            )
            return True

    def complete_result(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        result: EmpiricalResult,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            case = self._bump(conn, case)
            conn.execute(
                "UPDATE results SET payload_json = ?, vintage = ? "
                "WHERE run_id = ? AND case_id = ?",
                (
                    result.model_dump_json(),
                    result.input_snapshot.vintage,
                    result.run_id,
                    result.case_id,
                ),
            )
            response = {
                "case_id": case.case_id,
                "revision": case.revision,
                "result": result.model_dump(mode="json"),
            }
            conn.execute(
                "INSERT INTO idempotency "
                "(case_id, idempotency_key, operation, response_json) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(case_id, idempotency_key) DO UPDATE SET "
                "response_json = excluded.response_json",
                (
                    case.case_id,
                    idempotency_key,
                    "request_test",
                    json.dumps(response),
                ),
            )
            return response

    def transact_result(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        result: EmpiricalResult,
    ) -> dict[str, Any]:
        return self.transact_queued_result(
            case, idempotency_key=idempotency_key, result=result
        )

    def transact_assessment(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        proposal: AgentProposal,
        assessment: HypothesisAssessment,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            case = self._bump(conn, case)
            conn.execute(
                "INSERT INTO proposals (proposal_id, case_id, payload_json) "
                "VALUES (?, ?, ?)",
                (proposal.proposal_id, proposal.case_id, proposal.model_dump_json()),
            )
            linked = assessment.model_copy(
                update={
                    "contributing_proposal_ids": [
                        *assessment.contributing_proposal_ids,
                        proposal.proposal_id,
                    ]
                }
            )
            self._write_assessment(conn, linked)
            response = {
                "case_id": case.case_id,
                "revision": case.revision,
                "proposal": proposal.model_dump(mode="json"),
                "assessment": linked.model_dump(mode="json"),
            }
            self.put_idempotent(
                conn, case.case_id, idempotency_key, "propose_assessment", response
            )
            return response

    def _write_assessment(
        self, conn: sqlite3.Connection, assessment: HypothesisAssessment
    ) -> None:
        conn.execute(
            "INSERT INTO assessments "
            "(hypothesis_id, case_id, revision, payload_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(hypothesis_id) DO UPDATE SET revision = excluded.revision, "
            "payload_json = excluded.payload_json",
            (
                assessment.hypothesis_id,
                assessment.case_id,
                assessment.revision,
                assessment.model_dump_json(),
            ),
        )
        conn.execute(
            "INSERT INTO assessment_history "
            "(hypothesis_id, revision, payload_json) VALUES (?, ?, ?)",
            (
                assessment.hypothesis_id,
                assessment.revision,
                assessment.model_dump_json(),
            ),
        )

    def _bump(self, conn: sqlite3.Connection, case: ResearchCase) -> ResearchCase:
        from datetime import UTC, datetime

        updated = case.model_copy(
            update={
                "revision": case.revision + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        conn.execute(
            "UPDATE cases SET revision = ?, payload_json = ? WHERE case_id = ?",
            (updated.revision, updated.model_dump_json(), updated.case_id),
        )
        return updated
