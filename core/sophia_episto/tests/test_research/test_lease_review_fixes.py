"""P1 lease-review fixes: atomic ledger writes and bound citations."""

from __future__ import annotations

import threading

from sophia_episto.research.contracts import (
    AllowedUse,
    HypothesisAssessment,
    HypothesisRecordStatus,
    MechanismHypothesis,
    ResultStatus,
    Sign,
    VariableSpec,
)
from sophia_episto.research.engine import ResearchEngine
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode
from sophia_episto.research.ledger import ResearchLedger
from tests.test_research.helpers import FakeRunner, snapshot
from tests.test_research.test_acceptance import _open, _propose


def _request(engine, case_id, revision, hypothesis_id, key, vintage="v1"):
    return engine.request_test(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": case_id,
            "expected_revision": revision,
            "idempotency_key": key,
            "hypothesis_id": hypothesis_id,
            "method": "granger_predictive",
            "question_type": "predictive",
            "input": snapshot(vintage, [0.1, 0.2], [0.2, 0.3]).model_dump(),
        }
    )


def _assess(engine, case_id, revision, hypothesis_id, key, cited_result_ids):
    return engine.propose_assessment(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": case_id,
            "expected_revision": revision,
            "idempotency_key": key,
            "hypothesis_id": hypothesis_id,
            "cited_result_ids": cited_result_ids,
            "requested_uses": ["explain", "predict"],
            "rationale": "Cite this run as support.",
        }
    )


def test_expected_revision_checked_inside_write_transaction(db_path):
    engine = ResearchEngine(db_path, runner=FakeRunner())
    opened = _open(engine)
    other = ResearchLedger(db_path)
    successes: list[dict] = []
    errors: list[ProtocolError] = []
    barrier = threading.Barrier(2)

    def write(ledger: ResearchLedger, key: str) -> None:
        cause = VariableSpec(variable_id="inflation_surprise", definition="surprise")
        effect = VariableSpec(variable_id="policy_path", definition="path")
        hypothesis = MechanismHypothesis(
            hypothesis_id=f"hyp-{key}",
            revision=1,
            case_id=opened["case_id"],
            cause_variable_id=cause.variable_id,
            effect_variable_id=effect.variable_id,
            channel=key,
            sign=Sign.UNKNOWN,
            submitting_actor="agent-a",
        )
        assessment = HypothesisAssessment(
            hypothesis_id=hypothesis.hypothesis_id,
            case_id=opened["case_id"],
            status=HypothesisRecordStatus.CANDIDATE,
        )
        case = ledger.require_case(opened["case_id"])
        barrier.wait()
        try:
            successes.append(
                ledger.transact_hypothesis(
                    case,
                    idempotency_key=key,
                    hypothesis=hypothesis,
                    assessment=assessment,
                    variables=[cause, effect],
                    expected_revision=opened["revision"],
                )
            )
        except ProtocolError as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=write, args=(engine.ledger, "conn-a")),
        threading.Thread(target=write, args=(other, "conn-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(successes) == 1
    assert len(errors) == 1
    assert errors[0].code == ProtocolErrorCode.STALE_REVISION
    assert engine.explain_case({"case_id": opened["case_id"]})["revision"] == opened[
        "revision"
    ] + 1


def test_terminal_result_does_not_regress_across_connections(db_path):
    engine = ResearchEngine(db_path, runner=FakeRunner())
    opened = _open(engine)
    proposed = _propose(
        engine,
        opened["case_id"],
        opened["revision"],
        "agent-a",
        "reaction_function",
        "positive",
        "hyp-1",
    )
    ran = _request(
        engine,
        opened["case_id"],
        proposed["revision"],
        proposed["hypothesis"]["hypothesis_id"],
        "run-1",
    )
    assert ran["result"]["status"] == ResultStatus.SUCCEEDED.value

    stored = engine.ledger.get_result(ran["result"]["run_id"])
    assert stored is not None
    other = ResearchLedger(db_path)
    pending = stored.model_copy(update={"status": ResultStatus.RUNNING})
    projected = other.project_result(
        pending, idempotency_key="regress-project", pending=True
    )
    assert projected["result"]["status"] == ResultStatus.SUCCEEDED.value
    assert (
        engine.ledger.get_result(ran["result"]["run_id"]).status
        == ResultStatus.SUCCEEDED
    )

    queued = stored.model_copy(update={"status": ResultStatus.QUEUED})
    completed = other.complete_result(
        engine.ledger.require_case(opened["case_id"]),
        idempotency_key="regress-complete",
        result=queued,
    )
    assert completed["result"]["status"] == ResultStatus.SUCCEEDED.value
    assert completed["revision"] == ran["revision"]
    assert (
        engine.ledger.get_result(ran["result"]["run_id"]).status
        == ResultStatus.SUCCEEDED
    )


def test_foreign_case_result_does_not_grant_explain_or_predict(engine, db_path):
    first = _open(engine)
    other = ResearchEngine(db_path, runner=FakeRunner())
    second = other.open_case(
        {
            "protocol_version": "1",
            "actor": "agent-b",
            "question": "A different case that must not leak permissions",
        }
    )
    hyp_a = _propose(
        engine, first["case_id"], first["revision"], "agent-a",
        "reaction_function", "positive", "a",
    )
    hyp_b = _propose(
        other, second["case_id"], second["revision"], "agent-b",
        "reaction_function", "positive", "b",
    )
    run_b = _request(
        other,
        second["case_id"],
        hyp_b["revision"],
        hyp_b["hypothesis"]["hypothesis_id"],
        "iso-b",
        vintage="v-b",
    )
    assessed = _assess(
        engine,
        first["case_id"],
        hyp_a["revision"],
        hyp_a["hypothesis"]["hypothesis_id"],
        "steal-b",
        [run_b["result"]["run_id"]],
    )
    assessment = assessed["assessment"]
    assert assessment["allowed_uses"] == []
    assert "cited_records_not_bound" in assessment["unmet_requirements"]
    assert assessment["status"] == HypothesisRecordStatus.UNMET_REQUIREMENTS.value


def test_other_hypothesis_result_does_not_grant_explain_or_predict(engine):
    opened = _open(engine)
    hyp_a = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-a",
    )
    hyp_b = _propose(
        engine, opened["case_id"], hyp_a["revision"], "agent-a",
        "growth_channel", "negative", "hyp-b",
    )
    run_b = _request(
        engine,
        opened["case_id"],
        hyp_b["revision"],
        hyp_b["hypothesis"]["hypothesis_id"],
        "run-b",
        vintage="v-b",
    )
    assessed = _assess(
        engine,
        opened["case_id"],
        run_b["revision"],
        hyp_a["hypothesis"]["hypothesis_id"],
        "cross-hyp",
        [run_b["result"]["run_id"]],
    )
    assessment = assessed["assessment"]
    assert AllowedUse.EXPLAIN.value not in assessment["allowed_uses"]
    assert AllowedUse.PREDICT.value not in assessment["allowed_uses"]
    assert "cited_records_not_bound" in assessment["unmet_requirements"]


def test_bound_result_still_grants_predict(engine):
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
    )
    ran = _request(
        engine,
        opened["case_id"],
        proposed["revision"],
        proposed["hypothesis"]["hypothesis_id"],
        "run-1",
    )
    assessed = _assess(
        engine,
        opened["case_id"],
        ran["revision"],
        proposed["hypothesis"]["hypothesis_id"],
        "bound",
        [ran["result"]["run_id"]],
    )
    assert AllowedUse.PREDICT.value in assessed["assessment"]["allowed_uses"]
    assert AllowedUse.EXPLAIN.value in assessed["assessment"]["allowed_uses"]
