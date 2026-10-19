from __future__ import annotations

import sys

from outside_research_agent.sophia import SophiaProtocolError
from outside_research_agent.workflow import resume_case, run_case
from tests.helpers import EPISTO_SRC, demo_observations

if str(EPISTO_SRC) not in sys.path:
    sys.path.insert(0, str(EPISTO_SRC))

from sophia_episto.research.contracts import (  # noqa: E402
    EmpiricalResult,
    MethodCapability,
    QuestionType,
    ResultStatus,
)
from sophia_episto.research.engine import ResearchEngine  # noqa: E402
from sophia_episto.research.errors import ProtocolError  # noqa: E402


class _ScriptedSophia:
    def __init__(self, *, pending: bool = True) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.pending = pending
        self.revision = 1

    def invoke(self, operation: str, payload: dict) -> dict:
        self.calls.append((operation, payload))
        if operation == "capabilities":
            return {"methods": [{"name": "granger_predictive", "available": True}]}
        if operation == "open_case":
            return {"case_id": "case-1", "revision": 1}
        if operation == "submit_evidence":
            self.revision = 2
            return {"revision": 2, "contribution_ids": ["ev-1"]}
        if operation == "propose_hypothesis":
            self.revision += 1
            return {
                "revision": self.revision,
                "hypothesis": {"hypothesis_id": f"hyp-{payload['channel']}"},
            }
        if operation == "request_test":
            self.revision += 1
            if self.pending:
                return {
                    "pending": True,
                    "revision": self.revision,
                    "result": {"run_id": "run-pending", "status": "running"},
                }
            return {
                "revision": self.revision,
                "result": {"run_id": "run-done", "status": "succeeded"},
            }
        if operation == "propose_assessment":
            return {"assessment": {"allowed_uses": ["explain", "predict"]}}
        if operation == "explain_case":
            return {
                "question": "Does an inflation surprise change the expected US policy path",
                "scope": {"jurisdiction": "US", "horizon": "4 quarters"},
                "source_claims": [],
                "hypotheses": [],
                "computed_results": [],
                "agent_interpretations": [],
            }
        raise AssertionError(f"unexpected operation {operation}")


class _PendingRunner:
    def capabilities(self) -> list[MethodCapability]:
        return [
            MethodCapability(
                name="granger_predictive",
                available=True,
                question_types=[QuestionType.PREDICTIVE, QuestionType.ASSOCIATION],
                required_inputs=["source_observations", "target_observations", "vintage"],
            )
        ]

    def run(self, **kwargs):
        return EmpiricalResult(
            run_id=kwargs["run_id"],
            case_id=kwargs["case_id"],
            hypothesis_id=kwargs["hypothesis_id"],
            fingerprint=kwargs["fingerprint"],
            method=kwargs["method"],
            method_version="pending-1",
            question_type=QuestionType.PREDICTIVE,
            estimand="predictive_granger",
            status=ResultStatus.RUNNING,
            input_snapshot=kwargs["snapshot"],
            assumptions=["execution_in_progress"],
            scope_limitations=["pending_run"],
            identification_resolved=False,
        )


class _EngineSophia:
    def __init__(self, engine: ResearchEngine) -> None:
        self.engine = engine

    def invoke(self, operation: str, payload: dict | None = None) -> dict:
        try:
            return self.engine.dispatch(operation, payload or {})
        except ProtocolError as exc:
            raise SophiaProtocolError(exc.to_dict(), returncode=2) from exc


def _claim() -> dict:
    return {
        "namespace": "notes",
        "occurrence_id": "c1",
        "snapshot_hash": "snap-1",
        "locations": ["p.1"],
        "excerpt": "Inflation surprise may move the policy path.",
    }


def test_pending_test_is_not_cited_as_evidence() -> None:
    sophia = _ScriptedSophia(pending=True)
    result = run_case(
        sophia,  # type: ignore[arg-type]
        actor="agent-a",
        claims=[{"namespace": "n", "occurrence_id": "1"}],
        observations={
            "vintage": "v1",
            "source_observations": [],
            "target_observations": [],
        },
    )
    assess = [payload for op, payload in sophia.calls if op == "propose_assessment"]
    assert assess == []
    assert result["assessment"] is None
    assert result["test"]["pending"] is True
    assert result["test"]["result"]["run_id"] == "run-pending"
    assert result["run_id"] == "run-pending"
    assert result["revision"] == result["test"]["revision"]
    assert result["revision"] > 4


def test_terminal_test_is_cited() -> None:
    sophia = _ScriptedSophia(pending=False)
    run_case(
        sophia,  # type: ignore[arg-type]
        actor="agent-a",
        claims=[{"namespace": "n", "occurrence_id": "1"}],
        observations={
            "vintage": "v1",
            "source_observations": [],
            "target_observations": [],
        },
    )
    assess = [payload for op, payload in sophia.calls if op == "propose_assessment"]
    assert assess[0]["cited_result_ids"] == ["run-done"]
    assert assess[0]["expected_revision"] == 5


def test_pending_path_against_real_ledger_defers_assessment(tmp_path) -> None:
    engine = ResearchEngine(tmp_path / "research.sqlite", runner=_PendingRunner())
    sophia = _EngineSophia(engine)
    result = run_case(
        sophia,  # type: ignore[arg-type]
        actor="agent-a",
        claims=[_claim()],
        observations=demo_observations(),
    )
    assert result["test"].get("pending") is True
    assert result["test"]["result"]["status"] == "running"
    assert result["run_id"] == result["test"]["result"]["run_id"]
    assert result["revision"] == result["test"]["revision"]
    assert result["revision"] > result["hypotheses"][1]["revision"]
    assert result["assessment"] is None

    live = engine.get_case({"case_id": result["case_id"]})
    assert live["revision"] == result["revision"]
    assert live["pending_runs"]
    assert live["pending_runs"][0]["run_id"] == result["run_id"]

    resumed = resume_case(sophia, case_id=result["case_id"])  # type: ignore[arg-type]
    assert resumed["case"]["revision"] == result["revision"]
    assert resumed["runs"]
    assert resumed["runs"][0]["result"]["run_id"] == result["run_id"]
    assert resumed["runs"][0]["result"]["status"] == "running"
    assert not resumed["explanation"].get("agent_interpretations")
