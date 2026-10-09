from __future__ import annotations

import threading

import pytest

from sophia_episto.research.engine import ResearchEngine
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode
from tests.test_research.helpers import FakeRunner, snapshot
from tests.test_research.test_acceptance import _open, _propose


def _test_payload(case_id: str, revision: int, hypothesis_id: str, key: str) -> dict:
    return {
        "protocol_version": "1",
        "actor": "agent-a",
        "case_id": case_id,
        "expected_revision": revision,
        "idempotency_key": key,
        "hypothesis_id": hypothesis_id,
        "method": "granger_predictive",
        "question_type": "predictive",
        "input": snapshot("v1", [0.1, 0.2, 0.3], [0.2, 0.3, 0.4]).model_dump(),
    }


def test_fake_runner_in_process_crash_leaves_queued_for_retry(db_path):
    """FakeRunner is for policy tests. An in-process exception is not a lease.

    Recovery of a live coordinator worker is covered by test_execution_lease.py.
    """
    class CrashOnceRunner(FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def run(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("interrupted before completion")
            return super().run(**kwargs)

    runner = CrashOnceRunner()
    engine = ResearchEngine(db_path, runner=runner)
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
    payload = _test_payload(
        opened["case_id"],
        proposed["revision"],
        proposed["hypothesis"]["hypothesis_id"],
        "run-crash",
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        engine.request_test(payload)
    pending = engine.get_case({"case_id": opened["case_id"]})
    assert pending["pending_runs"]
    assert pending["pending_runs"][0]["status"] == "queued"
    recovered = engine.request_test(payload)
    assert recovered["result"]["status"] == "succeeded"
    assert runner.attempts == 2


def test_replay_after_success_does_not_rerun(engine):
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
    payload = _test_payload(
        opened["case_id"],
        proposed["revision"],
        proposed["hypothesis"]["hypothesis_id"],
        "run-once",
    )
    first = engine.request_test(payload)
    second = engine.request_test(payload)
    assert second["result"]["run_id"] == first["result"]["run_id"]
    assert engine.runner.calls  # type: ignore[attr-defined]
    assert len(engine.runner.calls) == 1  # type: ignore[attr-defined]


def test_concurrent_clients_one_fingerprint(db_path, tmp_path):
    pytest.importorskip("sophia_oikonomia")
    from tests.test_research.test_execution_lease import CountingAdapter, _engine

    counter = tmp_path / "calls"
    opened_engine = _engine(db_path, tmp_path / "oiko.db", CountingAdapter(counter))
    opened = _open(opened_engine)
    proposed = _propose(
        opened_engine,
        opened["case_id"],
        opened["revision"],
        "agent-a",
        "reaction_function",
        "positive",
        "hyp-1",
    )
    results: list[dict] = []
    errors: list[BaseException] = []

    def worker(key: str) -> None:
        try:
            engine = _engine(db_path, tmp_path / "oiko.db", CountingAdapter(counter))
            results.append(
                engine.request_test(
                    _test_payload(
                        opened["case_id"],
                        proposed["revision"],
                        proposed["hypothesis"]["hypothesis_id"],
                        key,
                    )
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("c1",)),
        threading.Thread(target=worker, args=("c2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    run_ids = {item["result"]["run_id"] for item in results}
    assert len(run_ids) == 1
    final = opened_engine.explain_case({"case_id": opened["case_id"]})
    completed = [item for item in final["computed_results"] if item["status"] == "succeeded"]
    assert len(completed) == 1
    assert counter.read_text() == "1"


def test_oikonomia_runner_coordinates_granger(db_path, tmp_path):
    pytest.importorskip("sophia_oikonomia")
    pytest.importorskip("sophia_arithmos")
    from sophia_episto.research.oikonomia_runner import OikonomiaMethodRunner

    engine = ResearchEngine(
        db_path,
        runner=OikonomiaMethodRunner(tmp_path / "oikonomia.sqlite"),
    )
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
    import numpy as np

    rng = np.random.default_rng(0)
    y = rng.normal(size=40).cumsum().tolist()
    x = [value + 0.1 for value in y]
    result = engine.request_test(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": proposed["revision"],
            "idempotency_key": "oiko-1",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "method": "granger_predictive",
            "input": snapshot("v1", x, y).model_dump(),
        }
    )
    assert result["result"]["status"] in {"succeeded", "failed"}
    assert result["result"]["identification_resolved"] is False
    assert result["result"]["diagnostics"]["oikonomia_run_id"]
    replay = engine.request_test(
        {
            "protocol_version": "1",
            "actor": "agent-a",
            "case_id": opened["case_id"],
            "expected_revision": proposed["revision"],
            "idempotency_key": "oiko-1",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "method": "granger_predictive",
            "input": snapshot("v1", x, y).model_dump(),
        }
    )
    assert replay["result"]["run_id"] == result["result"]["run_id"]


def test_counterfactual_still_rejected_before_queue(engine):
    opened = _open(engine)
    with pytest.raises(ProtocolError) as exc:
        engine.request_test(
            {
                "protocol_version": "1",
                "actor": "agent-a",
                "case_id": opened["case_id"],
                "expected_revision": opened["revision"],
                "idempotency_key": "cf",
                "method": "granger_predictive",
                "question_type": "counterfactual",
                "input": snapshot("v1", [0.1], [0.2]).model_dump(),
            }
        )
    assert exc.value.code == ProtocolErrorCode.UNSUPPORTED_QUESTION
    assert engine.explain_case({"case_id": opened["case_id"]})["pending_runs"] == []
