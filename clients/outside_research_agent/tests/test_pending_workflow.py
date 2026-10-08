from __future__ import annotations

from outside_research_agent.workflow import run_case


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
            if self.pending:
                return {
                    "pending": True,
                    "revision": self.revision,
                    "result": {"run_id": "run-pending", "status": "running"},
                }
            return {
                "revision": self.revision + 1,
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
    assert assess
    assert assess[0]["cited_result_ids"] == []
    assert result["test"]["pending"] is True
    assert result["test"]["result"]["run_id"] == "run-pending"


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
