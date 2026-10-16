"""SQLite research-case ledger.

Evidence acceptance and the resulting assessment revision are written in one
BEGIN IMMEDIATE transaction: live state, expected revision, and writes share a
connection. Terminal results cannot be rewritten as queued or running.
Contribution IDs, idempotency keys, and run fingerprints are unique.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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


TERMINAL_RESULT_STATUSES = {
    ResultStatus.SUCCEEDED,
    ResultStatus.FAILED,
    ResultStatus.UNAVAILABLE,
}


def semantic_request_digest(operation: str, payload: dict[str, Any]) -> str:
    """Hash computation-defining inputs. Actor and transport metadata are excluded."""
    material = {
        "operation": operation,
        "case_id": payload.get("case_id"),
        "method": payload.get("method"),
        "question_type": payload.get("question_type"),
        "hypothesis_id": payload.get("hypothesis_id"),
        "input": payload.get("input"),
    }
    encoded = json.dumps(material, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
        conn.isolation_level = None
        return conn

    @contextmanager
    def _immediate(self) -> Iterator[sqlite3.Connection]:
        """One reserved transaction for state checks and writes."""
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
            idempotency_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(idempotency)").fetchall()
            }
            if "request_digest" not in idempotency_columns:
                conn.execute(
                    "ALTER TABLE idempotency ADD COLUMN request_digest TEXT"
                )

    def get_idempotent(
        self,
        case_id: str,
        idempotency_key: str,
        *,
        digest: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            return self._load_idempotent(
                conn, case_id, idempotency_key, digest=digest
            )

    def put_idempotent(
        self,
        conn: sqlite3.Connection,
        case_id: str,
        idempotency_key: str,
        operation: str,
        response: dict[str, Any],
        *,
        digest: str | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO idempotency "
            "(case_id, idempotency_key, operation, response_json, request_digest) "
            "VALUES (?, ?, ?, ?, ?)",
            (case_id, idempotency_key, operation, json.dumps(response), digest),
        )

    def save_case(self, case: ResearchCase) -> None:
        payload = case.model_dump(mode="json")
        with self._lock, self._immediate() as conn:
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
        return self._bump(conn, case)

    def save_variable(self, variable: VariableSpec) -> None:
        with self._lock, self._immediate() as conn:
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
        with self._lock, self._immediate() as conn:
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
        digest: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Insert new contributions and bump the case revision atomically."""
        with self._lock, self._immediate() as conn:
            replay = self._load_idempotent(
                conn, case.case_id, idempotency_key, digest=digest
            )
            if replay is not None:
                return replay
            live = self._require_expected_revision(
                conn, case.case_id, expected_revision
            )
            created = list(new_contributions)
            if created:
                still_new: list[EvidenceAssessment] = []
                for item in created:
                    row = conn.execute(
                        "SELECT contribution_id FROM contributions "
                        "WHERE contribution_id = ?",
                        (item.contribution_id,),
                    ).fetchone()
                    if row is None:
                        still_new.append(item)
                    elif item.contribution_id not in existing_ids:
                        existing_ids.append(item.contribution_id)
                created = still_new
            if created:
                live = self._bump(conn, live)
                for item in created:
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
                "case_id": live.case_id,
                "revision": live.revision,
                "contribution_ids": existing_ids
                + [item.contribution_id for item in created],
                "independence_groups": sorted(set(independence_groups)),
                "created_contribution_ids": [
                    item.contribution_id for item in created
                ],
                "provenance": [
                    {
                        "contribution_id": item.contribution_id,
                        "status": item.provenance_status.value,
                    }
                    for item in created
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
                conn,
                live.case_id,
                idempotency_key,
                "submit_evidence",
                response,
                digest=digest,
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
        digest: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock, self._immediate() as conn:
            replay = self._load_idempotent(
                conn, case.case_id, idempotency_key, digest=digest
            )
            if replay is not None:
                return replay
            live = self._require_expected_revision(
                conn, case.case_id, expected_revision
            )
            live = self._bump(conn, live)
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
                "case_id": live.case_id,
                "revision": live.revision,
                "hypothesis": hypothesis.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            }
            self.put_idempotent(
                conn,
                live.case_id,
                idempotency_key,
                "propose_hypothesis",
                response,
                digest=digest,
            )
            return response

    def transact_queued_result(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        result: EmpiricalResult,
        digest: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock, self._immediate() as conn:
            replay = self._load_idempotent(
                conn, case.case_id, idempotency_key, digest=digest
            )
            if replay is not None:
                return replay
            existing = conn.execute(
                "SELECT payload_json FROM results WHERE fingerprint = ?",
                (result.fingerprint,),
            ).fetchone()
            if existing is not None:
                loaded = EmpiricalResult.model_validate_json(existing["payload_json"])
                live = self._load_case(conn, case.case_id)
                response = {
                    "case_id": live.case_id,
                    "revision": live.revision,
                    "result": loaded.model_dump(mode="json"),
                    "replayed": True,
                }
                self.put_idempotent(
                    conn,
                    live.case_id,
                    idempotency_key,
                    "request_test",
                    response,
                    digest=digest,
                )
                return response
            live = self._require_expected_revision(
                conn, case.case_id, expected_revision
            )
            live = self._bump(conn, live)
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
                    "case_id": live.case_id,
                    "revision": live.revision,
                    "result": loaded.model_dump(mode="json"),
                    "replayed": True,
                }
                self.put_idempotent(
                    conn,
                    live.case_id,
                    idempotency_key,
                    "request_test",
                    response,
                    digest=digest,
                )
                return response
            response = {
                "case_id": live.case_id,
                "revision": live.revision,
                "result": result.model_dump(mode="json"),
            }
            self.put_idempotent(
                conn,
                live.case_id,
                idempotency_key,
                "request_test",
                response,
                digest=digest,
            )
            return response

    def claim_queued_run(self, result: EmpiricalResult) -> bool:
        """Atomically move a queued run to running. False if another client claimed it."""
        running = result.model_copy(update={"status": ResultStatus.RUNNING})
        with self._lock, self._immediate() as conn:
            current = self._load_result(conn, result.run_id)
            if current is None or current.status != ResultStatus.QUEUED:
                return False
            conn.execute(
                "UPDATE results SET payload_json = ? WHERE run_id = ?",
                (running.model_dump_json(), result.run_id),
            )
            return True

    def project_result(
        self,
        result: EmpiricalResult,
        *,
        idempotency_key: str | None = None,
        digest: str | None = None,
        pending: bool = True,
    ) -> dict[str, Any]:
        """Update a queued/running projection without bumping the case revision."""
        with self._lock, self._immediate() as conn:
            current = self._load_result(conn, result.run_id)
            if current is None:
                raise ProtocolError(
                    ProtocolErrorCode.NOT_FOUND, f"Unknown run: {result.run_id}"
                )
            stored = current
            if (
                current.status not in TERMINAL_RESULT_STATUSES
                and result.status not in TERMINAL_RESULT_STATUSES
            ):
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
                stored = result
            case = self._load_case(conn, result.case_id)
            response = {
                "case_id": case.case_id,
                "revision": case.revision,
                "result": stored.model_dump(mode="json"),
            }
            if pending:
                response["pending"] = True
            if idempotency_key:
                self._upsert_idempotent(
                    conn,
                    case.case_id,
                    idempotency_key,
                    "request_test",
                    response,
                    digest=digest,
                )
            return response

    def complete_result(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        result: EmpiricalResult,
        digest: str | None = None,
    ) -> dict[str, Any]:
        with self._lock, self._immediate() as conn:
            current = self._load_result(conn, result.run_id)
            if current is None:
                raise ProtocolError(
                    ProtocolErrorCode.NOT_FOUND, f"Unknown run: {result.run_id}"
                )
            live = self._load_case(conn, case.case_id)
            if current.status in TERMINAL_RESULT_STATUSES:
                stored = current
                replayed = True
            elif result.status not in TERMINAL_RESULT_STATUSES:
                stored = current
                replayed = True
            else:
                live = self._bump(conn, live)
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
                stored = result
                replayed = False
            response = {
                "case_id": live.case_id,
                "revision": live.revision,
                "result": stored.model_dump(mode="json"),
            }
            if replayed:
                response["replayed"] = True
            self._upsert_idempotent(
                conn,
                live.case_id,
                idempotency_key,
                "request_test",
                response,
                digest=digest,
            )
            return response

    def transact_result(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        result: EmpiricalResult,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        return self.transact_queued_result(
            case,
            idempotency_key=idempotency_key,
            result=result,
            expected_revision=expected_revision,
        )

    def transact_assessment(
        self,
        case: ResearchCase,
        *,
        idempotency_key: str,
        proposal: AgentProposal,
        assessment: HypothesisAssessment,
        digest: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        with self._lock, self._immediate() as conn:
            replay = self._load_idempotent(
                conn, case.case_id, idempotency_key, digest=digest
            )
            if replay is not None:
                return replay
            live = self._require_expected_revision(
                conn, case.case_id, expected_revision
            )
            live = self._bump(conn, live)
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
                "case_id": live.case_id,
                "revision": live.revision,
                "proposal": proposal.model_dump(mode="json"),
                "assessment": linked.model_dump(mode="json"),
            }
            self.put_idempotent(
                conn,
                live.case_id,
                idempotency_key,
                "propose_assessment",
                response,
                digest=digest,
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

    def _load_case(self, conn: sqlite3.Connection, case_id: str) -> ResearchCase:
        row = conn.execute(
            "SELECT payload_json FROM cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if row is None:
            raise ProtocolError(
                ProtocolErrorCode.NOT_FOUND,
                f"Unknown case: {case_id}",
            )
        return ResearchCase.model_validate_json(row["payload_json"])

    def _load_result(
        self, conn: sqlite3.Connection, run_id: str
    ) -> EmpiricalResult | None:
        row = conn.execute(
            "SELECT payload_json FROM results WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return EmpiricalResult.model_validate_json(row["payload_json"])

    def _load_idempotent(
        self,
        conn: sqlite3.Connection,
        case_id: str,
        idempotency_key: str,
        *,
        digest: str | None = None,
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT response_json, request_digest FROM idempotency "
            "WHERE case_id = ? AND idempotency_key = ?",
            (case_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        stored_digest = row["request_digest"]
        if digest is not None and stored_digest and stored_digest != digest:
            raise ProtocolError(
                ProtocolErrorCode.CONFLICT,
                "Idempotency key reused with a different request",
                details={
                    "idempotency_key": idempotency_key,
                    "case_id": case_id,
                },
            )
        return json.loads(row["response_json"])

    def _require_expected_revision(
        self,
        conn: sqlite3.Connection,
        case_id: str,
        expected_revision: int | None,
    ) -> ResearchCase:
        live = self._load_case(conn, case_id)
        if expected_revision is not None:
            self.require_revision(live, expected_revision)
        return live

    def _upsert_idempotent(
        self,
        conn: sqlite3.Connection,
        case_id: str,
        idempotency_key: str,
        operation: str,
        response: dict[str, Any],
        *,
        digest: str | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO idempotency "
            "(case_id, idempotency_key, operation, response_json, request_digest) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(case_id, idempotency_key) DO UPDATE SET "
            "response_json = excluded.response_json, "
            "request_digest = COALESCE(excluded.request_digest, request_digest)",
            (
                case_id,
                idempotency_key,
                operation,
                json.dumps(response),
                digest,
            ),
        )

    def _bump(self, conn: sqlite3.Connection, case: ResearchCase) -> ResearchCase:
        from datetime import UTC, datetime

        current = self._load_case(conn, case.case_id)
        updated = current.model_copy(
            update={
                "revision": current.revision + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        cursor = conn.execute(
            "UPDATE cases SET revision = ?, payload_json = ? "
            "WHERE case_id = ? AND revision = ?",
            (
                updated.revision,
                updated.model_dump_json(),
                updated.case_id,
                current.revision,
            ),
        )
        if cursor.rowcount != 1:
            live = self._load_case(conn, case.case_id)
            raise ProtocolError(
                ProtocolErrorCode.STALE_REVISION,
                "Stale case revision",
                details={
                    "expected_revision": current.revision,
                    "current_revision": live.revision,
                },
            )
        return updated
