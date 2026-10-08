from __future__ import annotations

import json
from pathlib import Path

import pytest

from sophia_episto.research.contracts import AllowedUse, HypothesisRecordStatus
from sophia_episto.research.engine import ResearchEngine
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode
from sophia_episto.research.runners import UnavailableRunner

from tests.test_research.helpers import FakeRunner, snapshot


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "research"
    / "non_analyst_bundle.json"
)


def _open(engine: ResearchEngine) -> dict:
    return engine.open_case(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "question": (
                "Does an inflation surprise change the expected US policy path "
                "over the next four quarters?"
            ),
            "scope": {
                "jurisdiction": "US",
                "measure": "core CPI surprise vs Bloomberg consensus",
                "surprise_baseline": "Bloomberg survey median",
                "horizon": "4 quarters",
                "competing_explanations": ["weaker growth lowering yields"],
            },
        }
    )


def _var(variable_id: str, definition: str) -> dict:
    return {
        "variable_id": variable_id,
        "definition": definition,
        "units": "percentage_points",
        "geography": "US",
        "frequency": "monthly",
    }


def _propose(engine, case_id, revision, actor, channel, sign, key):
    return engine.propose_hypothesis(
        {
            "protocol_version": "1",
            "actor": actor,
            "case_id": case_id,
            "expected_revision": revision,
            "idempotency_key": key,
            "cause": _var(
                "inflation_surprise",
                "Core CPI monthly surprise versus survey median",
            ),
            "effect": _var(
                "policy_path",
                "Four-quarter expected policy rate implied by OIS",
            ),
            "channel": channel,
            "sign": sign,
            "lag": "0-2 meetings",
            "alternatives": ["growth_channel"],
            "falsifiers": ["surprise with no path move after two meetings"],
            "rationale": "Agent-authored candidate mechanism",
        }
    )


def test_two_authors_one_release_share_independence_group(engine):
    opened = _open(engine)
    bundle = json.loads(FIXTURE.read_text())
    author_a = {
        **bundle,
        "namespace": "analyst",
        "occurrence_id": "cpi-2026-09:author-a:p3",
        "author": "Author A",
    }
    author_b = {
        **bundle,
        "namespace": "analyst",
        "occurrence_id": "cpi-2026-09:author-b:p1",
        "author": "Author B",
        "locations": ["page 1, paragraph 2"],
        "excerpt": "The same release is read as a growth shock, not a policy shock.",
    }
    submitted = engine.submit_evidence(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": opened["revision"],
            "idempotency_key": "ev-1",
            "claims": [author_a, author_b],
        }
    )
    assert len(submitted["contribution_ids"]) == 2
    assert submitted["independence_groups"] == ["release:cpi-2026-09"]
    snapshot_case = engine.get_case({"case_id": opened["case_id"]})
    authors = {
        item["claim"]["author"] for item in snapshot_case["source_claims"]
    }
    assert authors == {"Author A", "Author B"}


def test_opposing_mechanisms_share_endpoints(engine):
    opened = _open(engine)
    first = _propose(
        engine,
        opened["case_id"],
        opened["revision"],
        "agent-a",
        "reaction_function",
        "positive",
        "hyp-1",
    )
    second = _propose(
        engine,
        opened["case_id"],
        first["revision"],
        "agent-a",
        "growth_channel",
        "negative",
        "hyp-2",
    )
    snapshot_case = engine.get_case({"case_id": opened["case_id"]})
    assert len(snapshot_case["hypotheses"]) == 2
    ids = {item["hypothesis_id"] for item in snapshot_case["hypotheses"]}
    assert first["hypothesis"]["hypothesis_id"] in ids
    assert second["hypothesis"]["hypothesis_id"] in ids
    assert first["hypothesis"]["cause_variable_id"] == second["hypothesis"]["cause_variable_id"]
    assert first["assessment"]["status"] == HypothesisRecordStatus.CANDIDATE.value


def test_replay_and_restart_do_not_duplicate(engine, db_path):
    opened = _open(engine)
    bundle = json.loads(FIXTURE.read_text())
    first = engine.submit_evidence(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": opened["revision"],
            "idempotency_key": "same-key",
            "claims": [bundle],
        }
    )
    replay = engine.submit_evidence(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": opened["revision"],
            "idempotency_key": "same-key",
            "claims": [bundle],
        }
    )
    assert replay == first
    restarted = ResearchEngine(db_path, runner=FakeRunner())
    again = restarted.submit_evidence(
        {
            "protocol_version": "1",
            "actor": "agent-b",
            "case_id": opened["case_id"],
            "expected_revision": first["revision"],
            "idempotency_key": "other-key-same-bundle",
            "claims": [bundle],
        }
    )
    assert again["created_contribution_ids"] == []
    assert again["contribution_ids"] == first["contribution_ids"]
    assert again["revision"] == first["revision"]


def test_vintage_revision_preserves_as_of_result(engine):
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
    v1 = engine.request_test(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": proposed["revision"],
            "idempotency_key": "run-v1",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "method": "granger_predictive",
            "question_type": "predictive",
            "input": snapshot("v1", [0.1, 0.2, 0.0], [0.2, 0.3, 0.1]).model_dump(),
        }
    )
    v2 = engine.request_test(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": v1["revision"],
            "idempotency_key": "run-v2",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "method": "granger_predictive",
            "question_type": "predictive",
            "input": snapshot("v2", [0.1, 0.2, 0.4], [0.2, 0.3, 0.5]).model_dump(),
        }
    )
    assert v1["result"]["run_id"] != v2["result"]["run_id"]
    as_of = engine.explain_case(
        {"case_id": opened["case_id"], "as_of_vintage": "v1"}
    )
    assert [item["run_id"] for item in as_of["computed_results"]] == [
        v1["result"]["run_id"]
    ]


def test_invalid_citation_and_unavailable_method(db_path):
    engine = ResearchEngine(db_path, runner=UnavailableRunner())
    opened = _open(engine)
    submitted = engine.submit_evidence(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": opened["revision"],
            "idempotency_key": "bad-cite",
            "claims": [
                {
                    "namespace": "web",
                    "occurrence_id": "llm-cite-1",
                    "citation": "A paper somewhere",
                }
            ],
        }
    )
    assert submitted["provenance"][0]["status"] == "unverified"
    with pytest.raises(ProtocolError) as exc:
        engine.request_test(
            {
                "protocol_version": "1",
                "actor": "agent-a",
                "case_id": opened["case_id"],
                "expected_revision": submitted["revision"],
                "idempotency_key": "run-missing",
                "method": "granger_predictive",
                "question_type": "predictive",
                "input": snapshot("v1", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]).model_dump(),
            }
        )
    assert exc.value.code == ProtocolErrorCode.METHOD_UNAVAILABLE


def test_predictive_result_does_not_allow_intervention(engine):
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
    ran = engine.request_test(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": proposed["revision"],
            "idempotency_key": "run-1",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "method": "granger_predictive",
            "question_type": "predictive",
            "input": snapshot("v1", [0.1, 0.2], [0.2, 0.3]).model_dump(),
        }
    )
    assessed = engine.propose_assessment(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": ran["revision"],
            "idempotency_key": "assess-1",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "cited_result_ids": [ran["result"]["run_id"]],
            "requested_uses": ["explain", "predict", "intervene"],
            "rationale": "The association is useful for a bounded explanation.",
        }
    )
    assessment = assessed["assessment"]
    assert assessment["status"] == HypothesisRecordStatus.USEFUL_BOUNDED.value
    assert AllowedUse.PREDICT.value in assessment["allowed_uses"]
    assert AllowedUse.INTERVENE.value not in assessment["allowed_uses"]
    assert "causal_identification_unresolved" in assessment["unmet_requirements"]


def test_unsupported_counterfactual_has_no_path_product(engine):
    opened = _open(engine)
    with pytest.raises(ProtocolError) as exc:
        engine.request_test(
            {
                "protocol_version": "1",
                "actor": "agent-a",
                "case_id": opened["case_id"],
                "expected_revision": opened["revision"],
                "idempotency_key": "cf-1",
                "method": "granger_predictive",
                "question_type": "counterfactual",
                "input": snapshot("v1", [0.1], [0.2]).model_dump(),
            }
        )
    assert exc.value.code == ProtocolErrorCode.UNSUPPORTED_QUESTION
    assert "identified_causal_model" in exc.value.details["missing"]
    assert "direct_strength" not in exc.value.details
    assert "path_influence" not in exc.value.details


def test_prose_without_evidence_is_not_promoted(engine):
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
    assessed = engine.propose_assessment(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": proposed["revision"],
            "idempotency_key": "prose",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "requested_uses": ["intervene"],
            "rationale": "This is obviously causal if you think about it.",
        }
    )
    assert assessed["proposal"]["rationale"]
    assert assessed["assessment"]["status"] == HypothesisRecordStatus.UNMET_REQUIREMENTS.value
    assert "evidence_or_result_required" in assessed["assessment"]["unmet_requirements"]
    assert assessed["assessment"]["allowed_uses"] == []


def test_second_client_resumes_from_ids(engine, db_path):
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
    other = ResearchEngine(db_path, runner=FakeRunner())
    resumed = other.get_case({"case_id": opened["case_id"]})
    assert resumed["case_id"] == opened["case_id"]
    assert resumed["hypotheses"][0]["hypothesis_id"] == proposed["hypothesis"]["hypothesis_id"]
    assert resumed["question"]


def test_stale_revision_and_idempotent_replay(engine):
    opened = _open(engine)
    first = _propose(
        engine,
        opened["case_id"],
        opened["revision"],
        "agent-a",
        "reaction_function",
        "positive",
        "hyp-1",
    )
    with pytest.raises(ProtocolError) as exc:
        _propose(
            engine,
            opened["case_id"],
            opened["revision"],
            "agent-b",
            "growth_channel",
            "negative",
            "hyp-stale",
        )
    assert exc.value.code == ProtocolErrorCode.STALE_REVISION
    replay = engine.propose_hypothesis(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": opened["revision"],
            "idempotency_key": "hyp-1",
            "cause": _var("inflation_surprise", "Core CPI surprise"),
            "effect": _var("policy_path", "Expected policy path"),
            "channel": "reaction_function",
        }
    )
    assert replay["hypothesis"]["hypothesis_id"] == first["hypothesis"]["hypothesis_id"]


def test_generic_fixture_and_analyst_independence(engine):
    opened = _open(engine)
    bundle = json.loads(FIXTURE.read_text())
    submitted = engine.submit_evidence(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": opened["revision"],
            "idempotency_key": "generic",
            "claims": [bundle],
        }
    )
    explanation = engine.explain_case({"case_id": opened["case_id"]})
    assert explanation["source_claims"][0]["kind"] == "source_statement"
    assert submitted["contribution_ids"]
    assert explanation["revision"] == submitted["revision"]


def test_cli_round_trip(db_path, tmp_path):
    from sophia_episto.research.cli import main

    payload = tmp_path / "open.json"
    payload.write_text(
        json.dumps(
            {
                "protocol_version": "1",
                "actor": "cli-agent",
                "question": "CLI open",
            }
        ),
        encoding="utf-8",
    )
    assert main(["--db", str(db_path), "--payload", str(payload), "open_case"]) == 0
    assert main(["--db", str(db_path), "capabilities"]) == 0
