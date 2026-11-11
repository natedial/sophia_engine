"""Evidence contributions belong to a case (review finding 5).

The contribution ID is derived from the claim's content, so the same claim
has the same ID in every case. That ID is a cross-case identity; the
ledger row is keyed per case.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sophia_episto.research.ledger import ResearchLedger

CLAIM = {
    "namespace": "t",
    "occurrence_id": "o1",
    "content_hash": "h",
    "excerpt": "anything at all",
}

# The contributions table as it was created at 1f58c6b.
LEGACY_CONTRIBUTIONS_DDL = """
CREATE TABLE IF NOT EXISTS contributions (
    contribution_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    independence_group TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def _open(engine, question: str) -> dict:
    return engine.open_case({"protocol_version": "1", "actor": "r", "question": question})


def _submit(engine, case: dict, key: str = "e") -> dict:
    return engine.submit_evidence(
        {
            "protocol_version": "1",
            "actor": "r",
            "case_id": case["case_id"],
            "expected_revision": case["revision"],
            "idempotency_key": key,
            "claims": [CLAIM],
        }
    )


def _assess(engine, case_id: str, revision: int, cited: list[str]) -> dict:
    proposed = engine.propose_hypothesis(
        {
            "protocol_version": "1",
            "actor": "r",
            "case_id": case_id,
            "expected_revision": revision,
            "idempotency_key": "h",
            "cause": "x",
            "effect": "y",
        }
    )
    return engine.propose_assessment(
        {
            "protocol_version": "1",
            "actor": "r",
            "case_id": case_id,
            "expected_revision": proposed["revision"],
            "idempotency_key": "a",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "cited_evidence_ids": cited,
            "requested_uses": ["explain"],
        }
    )["assessment"]


def test_same_claim_in_two_cases_binds_in_both(engine):
    case_a = _open(engine, "qa")
    case_b = _open(engine, "qb")
    ev_a = _submit(engine, case_a)
    ev_b = _submit(engine, case_b)

    assert ev_b["provenance"][0]["status"] != "duplicate"
    assert ev_b["contribution_ids"] == ev_a["contribution_ids"]
    explained = engine.explain_case({"case_id": case_b["case_id"]})
    assert len(explained["source_claims"]) == 1

    assessment = _assess(engine, case_b["case_id"], ev_b["revision"], ev_b["contribution_ids"])
    assert "cited_records_not_bound" not in assessment["unmet_requirements"]
    assert "cited_records_not_found" not in assessment["unmet_requirements"]


def test_same_claim_same_case_is_still_duplicate(engine):
    case = _open(engine, "q")
    first = _submit(engine, case, key="e1")
    second = _submit(engine, {**case, "revision": first["revision"]}, key="e2")

    assert second["provenance"][0]["status"] == "duplicate"
    assert second["contribution_ids"] == first["contribution_ids"]
    assert len(engine.ledger.list_contributions(case["case_id"])) == 1


def test_citing_other_case_contribution_is_not_found(engine):
    case_a = _open(engine, "qa")
    case_b = _open(engine, "qb")
    ev_b = _submit(engine, case_b)

    assessment = _assess(engine, case_a["case_id"], case_a["revision"], ev_b["contribution_ids"])
    assert "cited_records_not_found" in assessment["unmet_requirements"]
    assert assessment["allowed_uses"] == []


def _pk_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("PRAGMA table_info(contributions)").fetchall()
    return {row[1] for row in rows if row[5]}


def test_legacy_contributions_table_is_migrated(engine, tmp_path):
    case = _open(engine, "q")
    submitted = _submit(engine, case)
    contribution_id = submitted["contribution_ids"][0]
    with sqlite3.connect(engine.ledger.db_path) as conn:
        row = conn.execute(
            "SELECT contribution_id, case_id, independence_group, payload_json "
            "FROM contributions"
        ).fetchone()

    legacy = tmp_path / "legacy.sqlite"
    with sqlite3.connect(legacy) as conn:
        conn.executescript(LEGACY_CONTRIBUTIONS_DDL)
        conn.execute("INSERT INTO contributions VALUES (?, ?, ?, ?)", row)
    assert _pk_columns(legacy) == {"contribution_id"}

    ledger = ResearchLedger(legacy)
    assert _pk_columns(legacy) == {"case_id", "contribution_id"}
    loaded = ledger.get_contribution(case["case_id"], contribution_id)
    assert loaded is not None
    assert loaded.contribution_id == contribution_id

    ResearchLedger(legacy)
    assert len(ledger.list_contributions(case["case_id"])) == 1
