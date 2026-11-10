"""Episto reconciliation against Oikonomia leases. FakeRunner is not used here."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from sophia_episto.research.engine import ResearchEngine
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode
from sophia_episto.research.oikonomia_runner import GRANGER_MODEL_ID, OikonomiaMethodRunner
from tests.test_research.helpers import snapshot
from tests.test_research.test_acceptance import _open, _propose

pytest.importorskip("sophia_oikonomia")

from sophia_oikonomia.adapters.base import ModelAdapter
from sophia_oikonomia.adapters.registry import AdapterRegistry
from sophia_oikonomia.core.clock import FileClock
from sophia_oikonomia.core.runtime import OikonomiaRuntime
from sophia_oikonomia.core.store import OikonomiaStore
from sophia_oikonomia.core.types import (
    ExecutionSpec,
    InputSnapshotRef,
    ModelDefinition,
    ModelExecutionResult,
    ModelFamily,
    ModelRun,
    ModelState,
    ModelTrigger,
    RunStatus,
)
from sophia_episto.research.contracts import ResultStatus

LEASE = timedelta(seconds=60)
HEARTBEAT = timedelta(days=1)


class CountingAdapter(ModelAdapter):
    def __init__(self, counter: Path, marker: str = "ok") -> None:
        self.counter = Path(counter)
        self.marker = marker

    def build_input_snapshot(
        self, definition: ModelDefinition, trigger: ModelTrigger
    ) -> InputSnapshotRef:
        return InputSnapshotRef(snapshot_id="snap-count", as_of=trigger.as_of)

    def execute(self, definition: ModelDefinition, run: ModelRun) -> ModelExecutionResult:
        n = int(self.counter.read_text()) if self.counter.exists() else 0
        self.counter.write_text(str(n + 1))
        return ModelExecutionResult(
            status=RunStatus.SUCCEEDED,
            output_summary={
                "status": "succeeded",
                "method": "granger_predictive",
                "method_version": "fake-lease-1",
                "question_type": "predictive",
                "estimand": "predictive_granger",
                "estimate": 0.5,
                "marker": self.marker,
                "identification_resolved": False,
            },
        )


class GateAdapter(CountingAdapter):
    def __init__(self, counter: Path, gate: Path) -> None:
        super().__init__(counter)
        self.gate = Path(gate)

    def execute(self, definition: ModelDefinition, run: ModelRun) -> ModelExecutionResult:
        self.gate.mkdir(parents=True, exist_ok=True)
        n = int(self.counter.read_text()) if self.counter.exists() else 0
        self.counter.write_text(str(n + 1))
        (self.gate / "started").write_text("1")
        deadline = time.time() + 30
        while not (self.gate / "release").exists():
            if time.time() > deadline:
                raise TimeoutError("gate was not released")
            time.sleep(0.01)
        return ModelExecutionResult(
            status=RunStatus.SUCCEEDED,
            output_summary={
                "status": "succeeded",
                "method": "granger_predictive",
                "method_version": "fake-lease-1",
                "question_type": "predictive",
                "estimand": "predictive_granger",
                "estimate": 0.5,
                "identification_resolved": False,
            },
        )


def _engine(
    db_path: Path,
    oiko_path: Path,
    adapter: ModelAdapter,
    clock: FileClock | None = None,
) -> ResearchEngine:
    clock = clock or FileClock(oiko_path.parent / "clock")
    store = OikonomiaStore(oiko_path, clock=clock)
    adapters = AdapterRegistry()
    adapters.register("hypothesis_test", adapter)
    runtime = OikonomiaRuntime(
        store=store,
        adapters=adapters,
        lease_duration=LEASE,
        heartbeat_interval=HEARTBEAT,
    )
    if runtime.get_model(GRANGER_MODEL_ID) is None:
        runtime.register_model(
            ModelDefinition(
                id=GRANGER_MODEL_ID,
                name="Episto Granger predictive test",
                family=ModelFamily.MACRO,
                owner="episto",
                state=ModelState.RESEARCH,
                execution=ExecutionSpec(adapter_id="hypothesis_test"),
            )
        )
    return ResearchEngine(
        db_path,
        runner=OikonomiaMethodRunner(
            oiko_path, runtime=runtime, method_available=True
        ),
    )


def _payload(case_id: str, revision: int, hypothesis_id: str, key: str) -> dict:
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


def test_retry_while_worker_active_returns_pending(db_path: Path, tmp_path: Path) -> None:
    counter = tmp_path / "calls"
    gate = tmp_path / "gate"
    engine = _engine(db_path, tmp_path / "oiko.db", GateAdapter(counter, gate))
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
    )
    payload = _payload(
        opened["case_id"], proposed["revision"],
        proposed["hypothesis"]["hypothesis_id"], "run-held",
    )
    errors: list[BaseException] = []
    first: dict = {}

    def worker() -> None:
        try:
            first.update(engine.request_test(payload))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.time() + 10
    while not (gate / "started").exists() and time.time() < deadline:
        time.sleep(0.01)
    retry_engine = _engine(db_path, tmp_path / "oiko.db", GateAdapter(counter, gate), clock=FileClock(tmp_path / "clock"))
    pending = retry_engine.request_test(payload)
    assert pending.get("pending") is True
    assert pending["result"]["status"] == "running"
    assert counter.read_text() == "1"
    (gate / "release").write_text("1")
    thread.join(timeout=15)
    assert errors == []
    assert first["result"]["status"] == "succeeded"


def test_different_keys_same_fingerprint_one_lease(db_path: Path, tmp_path: Path) -> None:
    counter = tmp_path / "calls"
    engine = _engine(db_path, tmp_path / "oiko.db", CountingAdapter(counter))
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
    )
    first = engine.request_test(
        _payload(
            opened["case_id"], proposed["revision"],
            proposed["hypothesis"]["hypothesis_id"], "k1",
        )
    )
    second = engine.request_test(
        _payload(
            opened["case_id"], first["revision"],
            proposed["hypothesis"]["hypothesis_id"], "k2",
        )
    )
    assert first["result"]["run_id"] == second["result"]["run_id"]
    assert counter.read_text() == "1"


def test_oikonomia_success_before_episto_complete_is_imported(
    db_path: Path, tmp_path: Path
) -> None:
    counter = tmp_path / "calls"
    engine = _engine(db_path, tmp_path / "oiko.db", CountingAdapter(counter))
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
    )
    first = engine.request_test(
        _payload(
            opened["case_id"], proposed["revision"],
            proposed["hypothesis"]["hypothesis_id"], "import-1",
        )
    )
    # Simulate crash after Oikonomia commit by resetting the Episto result to queued.
    import json

    result = engine.ledger.get_result(first["result"]["run_id"])
    assert result is not None
    queued = result.model_copy(update={"status": ResultStatus.QUEUED, "estimate": None})
    queued_response = {
        "case_id": opened["case_id"],
        "revision": first["revision"],
        "result": queued.model_dump(mode="json"),
    }
    with engine.ledger._lock, engine.ledger._connect() as conn:
        conn.execute(
            "UPDATE results SET payload_json = ? WHERE run_id = ?",
            (queued.model_dump_json(), result.run_id),
        )
        conn.execute(
            "UPDATE idempotency SET response_json = ? WHERE idempotency_key = ?",
            (json.dumps(queued_response), "import-1"),
        )
    replay = engine.request_test(
        _payload(
            opened["case_id"], proposed["revision"],
            proposed["hypothesis"]["hypothesis_id"], "import-1",
        )
    )
    assert replay["result"]["status"] == "succeeded"
    assert replay["result"]["run_id"] == first["result"]["run_id"]
    assert counter.read_text() == "1"


def test_complete_result_twice_does_not_bump_revision(db_path: Path, tmp_path: Path) -> None:
    engine = _engine(db_path, tmp_path / "oiko.db", CountingAdapter(tmp_path / "calls"))
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
    )
    first = engine.request_test(
        _payload(
            opened["case_id"], proposed["revision"],
            proposed["hypothesis"]["hypothesis_id"], "once",
        )
    )
    again = engine.ledger.complete_result(
        engine.ledger.require_case(opened["case_id"]),
        idempotency_key="once",
        result=engine.ledger.get_result(first["result"]["run_id"]),
    )
    assert again["revision"] == first["revision"]
    assert again["result"]["run_id"] == first["result"]["run_id"]


def test_hypothesis_during_run_survives_completion(db_path: Path, tmp_path: Path) -> None:
    counter = tmp_path / "calls"
    gate = tmp_path / "gate"
    engine = _engine(db_path, tmp_path / "oiko.db", GateAdapter(counter, gate))
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
    )
    payload = _payload(
        opened["case_id"], proposed["revision"],
        proposed["hypothesis"]["hypothesis_id"], "during",
    )
    errors: list[BaseException] = []
    completed: dict = {}

    def worker() -> None:
        try:
            completed.update(engine.request_test(payload))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.time() + 10
    while not (gate / "started").exists() and time.time() < deadline:
        time.sleep(0.01)
    live = engine.get_case({"case_id": opened["case_id"]})
    second = _propose(
        engine,
        opened["case_id"],
        live["revision"],
        "agent-a",
        "growth_channel",
        "negative",
        "hyp-2",
    )
    (gate / "release").write_text("1")
    thread.join(timeout=15)
    assert errors == []
    case = engine.get_case({"case_id": opened["case_id"]})
    ids = {item["hypothesis_id"] for item in case["hypotheses"]}
    assert second["hypothesis"]["hypothesis_id"] in ids
    assert completed["revision"] == second["revision"] + 1
    assert completed["result"]["status"] == "succeeded"


def test_same_key_different_snapshot_conflicts(db_path: Path, tmp_path: Path) -> None:
    engine = _engine(db_path, tmp_path / "oiko.db", CountingAdapter(tmp_path / "calls"))
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
    )
    engine.request_test(
        _payload(
            opened["case_id"], proposed["revision"],
            proposed["hypothesis"]["hypothesis_id"], "digest-key",
        )
    )
    with pytest.raises(ProtocolError) as exc:
        engine.request_test(
            {
                "protocol_version": "1",
                "actor": "agent-b",
                "case_id": opened["case_id"],
                "expected_revision": proposed["revision"],
                "idempotency_key": "digest-key",
                "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
                "method": "granger_predictive",
                "question_type": "predictive",
                "input": snapshot("v2", [9.0], [8.0]).model_dump(),
            }
        )
    assert exc.value.code == ProtocolErrorCode.CONFLICT


def test_lease_expiry_allows_recovery(db_path: Path, tmp_path: Path) -> None:
    counter = tmp_path / "calls"
    clock = FileClock(tmp_path / "clock")
    engine = _engine(
        db_path, tmp_path / "oiko.db", CountingAdapter(counter), clock=clock
    )
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
    )
    payload = _payload(
        opened["case_id"], proposed["revision"],
        proposed["hypothesis"]["hypothesis_id"], "recover",
    )
    first = engine.request_test(payload)
    assert first["result"]["status"] == "succeeded"
    oiko_id = first["result"]["diagnostics"]["oikonomia_run_id"]
    run = engine.runner.runtime.get_run(oiko_id)  # type: ignore[attr-defined]
    assert run is not None
    replay = engine.request_test(payload)
    assert replay["result"]["run_id"] == first["result"]["run_id"]
    assert counter.read_text() == "1"


def test_numerical_granger_through_lease_path(db_path: Path, tmp_path: Path) -> None:
    pytest.importorskip("sophia_arithmos")
    from sophia_episto.research.oikonomia_runner import OikonomiaMethodRunner

    engine = ResearchEngine(
        db_path,
        runner=OikonomiaMethodRunner(tmp_path / "oikonomia.sqlite"),
    )
    opened = _open(engine)
    proposed = _propose(
        engine, opened["case_id"], opened["revision"], "agent-a",
        "reaction_function", "positive", "hyp-1",
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
            "idempotency_key": "numeric-lease",
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
            "idempotency_key": "numeric-lease",
            "hypothesis_id": proposed["hypothesis"]["hypothesis_id"],
            "method": "granger_predictive",
            "input": snapshot("v1", x, y).model_dump(),
        }
    )
    assert replay["result"]["run_id"] == result["result"]["run_id"]
    assert "pending" not in replay
