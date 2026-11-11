"""Shape-checked provenance grants nothing on its own (review finding 3).

Nothing yet confirms that a claim's excerpt occurs in the source it names,
so a claim with an identity field and an excerpt is only well formed.
"""

from __future__ import annotations

import json
import sqlite3

from sophia_episto.research.contracts import ProvenanceStatus
from sophia_episto.research.engine import ResearchEngine
from sophia_episto.research.ledger import ResearchLedger

from tests.test_research.helpers import FakeRunner
from tests.test_research.test_case_scoped_evidence import CLAIM, _assess, _open


def _submit_payload(case: dict) -> dict:
    return {
        "protocol_version": "1",
        "actor": "r",
        "case_id": case["case_id"],
        "expected_revision": case["revision"],
        "idempotency_key": "e",
        "claims": [CLAIM],
    }


def test_well_formed_claim_alone_grants_nothing(engine):
    case = _open(engine, "q")
    submitted = engine.submit_evidence(_submit_payload(case))
    assert submitted["provenance"][0]["status"] == "well_formed"

    assessment = _assess(
        engine, case["case_id"], submitted["revision"], submitted["contribution_ids"]
    )
    assert assessment["status"] == "unmet_requirements"
    assert assessment["allowed_uses"] == []
    assert "verified_source_or_result_required" in assessment["unmet_requirements"]


def _mark_verified(db_path) -> None:
    """Rewrite stored records the way a ledger written before the rename holds them."""
    with sqlite3.connect(db_path) as conn:
        for key, payload in conn.execute(
            "SELECT contribution_id, payload_json FROM contributions"
        ).fetchall():
            data = json.loads(payload)
            data["provenance_status"] = "verified"
            conn.execute(
                "UPDATE contributions SET payload_json = ? WHERE contribution_id = ?",
                (json.dumps(data), key),
            )
        for case_id, key, response in conn.execute(
            "SELECT case_id, idempotency_key, response_json FROM idempotency "
            "WHERE operation = 'submit_evidence'"
        ).fetchall():
            data = json.loads(response)
            for item in data["provenance"]:
                item["status"] = "verified"
            conn.execute(
                "UPDATE idempotency SET response_json = ? "
                "WHERE case_id = ? AND idempotency_key = ?",
                (json.dumps(data), case_id, key),
            )


def test_stored_verified_status_is_rewritten(db_path):
    engine = ResearchEngine(db_path, runner=FakeRunner())
    case = _open(engine, "q")
    payload = _submit_payload(case)
    submitted = engine.submit_evidence(payload)
    contribution_id = submitted["contribution_ids"][0]
    _mark_verified(db_path)

    reopened = ResearchEngine(db_path, runner=FakeRunner())
    stored = reopened.ledger.get_contribution(case["case_id"], contribution_id)
    assert stored.provenance_status == ProvenanceStatus.WELL_FORMED
    replayed = reopened.submit_evidence(payload)
    assert replayed["provenance"][0]["status"] == "well_formed"

    ResearchLedger(db_path)
    again = ResearchLedger(db_path).get_contribution(case["case_id"], contribution_id)
    assert again.provenance_status == ProvenanceStatus.WELL_FORMED
