"""Execution-lease ownership, fencing, and crash-window tests.

Concurrency uses separate store instances (and processes) on one SQLite file
plus a shared FileClock. A process-local lock is not the correctness mechanism.
"""

from __future__ import annotations

import json
import multiprocessing
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sophia_oikonomia.adapters.base import ModelAdapter
from sophia_oikonomia.adapters.registry import AdapterRegistry
from sophia_oikonomia.core.clock import FileClock
from sophia_oikonomia.core.runtime import OikonomiaRuntime
from sophia_oikonomia.core.store import OikonomiaStore
from sophia_oikonomia.core.types import (
    ClaimKind,
    ExecutionSpec,
    FinishKind,
    InputSnapshotRef,
    ModelDefinition,
    ModelExecutionResult,
    ModelFamily,
    ModelRun,
    ModelState,
    ModelTrigger,
    RunStatus,
    TriggerType,
)

LEASE = timedelta(seconds=60)
HEARTBEAT = timedelta(days=1)


class FileGateAdapter(ModelAdapter):
    """Blocks until `release` exists; records calls in a counter file."""

    def __init__(self, gate_dir: Path, output: str = "alpha") -> None:
        self.gate_dir = Path(gate_dir)
        self.output = output

    def build_input_snapshot(
        self, definition: ModelDefinition, trigger: ModelTrigger
    ) -> InputSnapshotRef:
        return InputSnapshotRef(snapshot_id="snap-gate", as_of=trigger.as_of)

    def execute(self, definition: ModelDefinition, run: ModelRun) -> ModelExecutionResult:
        counter = self.gate_dir / "calls"
        started = self.gate_dir / "started"
        release = self.gate_dir / "release"
        n = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(n + 1))
        started.write_text(run.lease_owner or "")
        deadline = time.time() + 30
        while not release.exists():
            if time.time() > deadline:
                raise TimeoutError("gate was not released")
            time.sleep(0.01)
        return ModelExecutionResult(
            status=RunStatus.SUCCEEDED,
            output_summary={"marker": self.output, "generation": run.lease_generation},
        )


class InstantAdapter(ModelAdapter):
    def __init__(self, counter: Path, marker: str = "ok") -> None:
        self.counter = Path(counter)
        self.marker = marker

    def build_input_snapshot(
        self, definition: ModelDefinition, trigger: ModelTrigger
    ) -> InputSnapshotRef:
        return InputSnapshotRef(snapshot_id="snap-instant", as_of=trigger.as_of)

    def execute(self, definition: ModelDefinition, run: ModelRun) -> ModelExecutionResult:
        n = int(self.counter.read_text()) if self.counter.exists() else 0
        self.counter.write_text(str(n + 1))
        return ModelExecutionResult(
            status=RunStatus.SUCCEEDED,
            output_summary={"marker": self.marker, "generation": run.lease_generation},
        )


class BoomAdapter(ModelAdapter):
    def __init__(self, counter: Path) -> None:
        self.counter = Path(counter)

    def build_input_snapshot(
        self, definition: ModelDefinition, trigger: ModelTrigger
    ) -> InputSnapshotRef:
        return InputSnapshotRef(snapshot_id="snap-boom", as_of=trigger.as_of)

    def execute(self, definition: ModelDefinition, run: ModelRun) -> ModelExecutionResult:
        n = int(self.counter.read_text()) if self.counter.exists() else 0
        self.counter.write_text(str(n + 1))
        raise ValueError("adapter exploded")


def _runtime(
    tmp_path: Path,
    adapter: ModelAdapter,
    *,
    adapter_id: str = "gate",
) -> OikonomiaRuntime:
    clock = FileClock(tmp_path / "clock")
    store = OikonomiaStore(tmp_path / "oikonomia.db", clock=clock)
    adapters = AdapterRegistry()
    adapters.register(adapter_id, adapter)
    runtime = OikonomiaRuntime(
        store=store,
        adapters=adapters,
        lease_duration=LEASE,
        heartbeat_interval=HEARTBEAT,
    )
    runtime.register_model(
        ModelDefinition(
            id="m1",
            name="lease-test",
            family=ModelFamily.MACRO,
            owner="tests",
            state=ModelState.RESEARCH,
            execution=ExecutionSpec(adapter_id=adapter_id),
        )
    )
    return runtime


def _trigger(fingerprint: str) -> ModelTrigger:
    return ModelTrigger(
        trigger_type=TriggerType.MANUAL,
        as_of=datetime.now(UTC),
        model_ids=["m1"],
        payload={"fingerprint": fingerprint},
    )


def _claim_worker(
    db_path: str,
    clock_path: str,
    run_id: str,
    owner: str,
    out_path: str,
) -> None:
    store = OikonomiaStore(Path(db_path), clock=FileClock(Path(clock_path)))
    outcome = store.claim_run(run_id, owner, LEASE)
    Path(out_path).write_text(
        json.dumps(
            {
                "kind": outcome.kind.value,
                "generation": outcome.run.lease_generation,
                "owner": outcome.run.lease_owner,
            }
        )
    )


def test_retry_while_lease_held_is_pending(tmp_path: Path) -> None:
    gate = tmp_path / "gate"
    gate.mkdir()
    runtime = _runtime(tmp_path, FileGateAdapter(gate))
    queued = runtime.create_run("m1", _trigger("fp-1"), fingerprint="fp-1")
    first = runtime.store.claim_run(queued.id, "worker-a", LEASE)
    assert first.kind == ClaimKind.ACQUIRED
    pending = runtime.execute_run(queued.id)
    assert pending.status == RunStatus.RUNNING
    assert pending.lease_owner == "worker-a"
    assert not (gate / "calls").exists()


def test_heartbeat_keeps_lease_from_being_stolen(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, InstantAdapter(tmp_path / "calls"))
    queued = runtime.create_run("m1", _trigger("fp-hb"), fingerprint="fp-hb")
    claimed = runtime.store.claim_run(queued.id, "worker-a", LEASE)
    assert claimed.kind == ClaimKind.ACQUIRED
    clock: FileClock = runtime.store.clock  # type: ignore[assignment]
    assert runtime.store.renew_lease(queued.id, "worker-a", 1, LEASE)
    clock.advance(50)
    pending = runtime.store.claim_run(queued.id, "worker-b", LEASE)
    assert pending.kind == ClaimKind.PENDING
    clock.advance(20)
    stolen = runtime.store.claim_run(queued.id, "worker-b", LEASE)
    assert stolen.kind == ClaimKind.ACQUIRED
    assert stolen.run.lease_generation == 2


def test_expired_lease_increments_generation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, InstantAdapter(tmp_path / "calls"))
    queued = runtime.create_run("m1", _trigger("fp-exp"), fingerprint="fp-exp")
    first = runtime.store.claim_run(queued.id, "worker-a", LEASE)
    assert first.run.lease_generation == 1
    clock: FileClock = runtime.store.clock  # type: ignore[assignment]
    clock.advance(61)
    second = runtime.store.claim_run(queued.id, "worker-b", LEASE)
    assert second.kind == ClaimKind.ACQUIRED
    assert second.run.lease_generation == 2
    assert second.run.lease_owner == "worker-b"


def test_stale_renew_and_finish_are_rejected(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, InstantAdapter(tmp_path / "calls", marker="b"))
    queued = runtime.create_run("m1", _trigger("fp-stale"), fingerprint="fp-stale")
    a = runtime.store.claim_run(queued.id, "worker-a", LEASE)
    clock: FileClock = runtime.store.clock  # type: ignore[assignment]
    clock.advance(61)
    b = runtime.store.claim_run(queued.id, "worker-b", LEASE)
    assert b.kind == ClaimKind.ACQUIRED
    assert not runtime.store.renew_lease(
        queued.id, "worker-a", a.run.lease_generation, LEASE
    )
    stale = queued.model_copy(
        update={
            "status": RunStatus.SUCCEEDED,
            "output_summary": {"marker": "stale-a"},
        }
    )
    rejected = runtime.store.finish_run(
        queued.id, "worker-a", a.run.lease_generation, stale
    )
    assert rejected.kind == FinishKind.REJECTED
    winner = b.run.model_copy(
        update={
            "status": RunStatus.SUCCEEDED,
            "output_summary": {"marker": "b"},
        }
    )
    accepted = runtime.store.finish_run(
        queued.id, "worker-b", b.run.lease_generation, winner
    )
    assert accepted.kind == FinishKind.ACCEPTED
    loaded = runtime.store.get_run(queued.id)
    assert loaded is not None
    assert loaded.output_summary["marker"] == "b"
    again = runtime.store.finish_run(
        queued.id, "worker-a", a.run.lease_generation, stale
    )
    assert again.kind == FinishKind.ALREADY_TERMINAL
    assert again.run.output_summary["marker"] == "b"


def test_two_processes_race_expired_lease(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, InstantAdapter(tmp_path / "calls"))
    queued = runtime.create_run("m1", _trigger("fp-race"), fingerprint="fp-race")
    runtime.store.claim_run(queued.id, "worker-a", LEASE)
    clock: FileClock = runtime.store.clock  # type: ignore[assignment]
    clock.advance(61)
    out_b = tmp_path / "b.json"
    out_c = tmp_path / "c.json"
    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(
            target=_claim_worker,
            args=(
                str(runtime.store.db_path),
                str(tmp_path / "clock"),
                queued.id,
                owner,
                str(path),
            ),
        )
        for owner, path in (("worker-b", out_b), ("worker-c", out_c))
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=15)
        assert proc.exitcode == 0
    results = [json.loads(path.read_text()) for path in (out_b, out_c)]
    acquired = [item for item in results if item["kind"] == ClaimKind.ACQUIRED.value]
    pending = [item for item in results if item["kind"] == ClaimKind.PENDING.value]
    assert len(acquired) == 1
    assert len(pending) == 1
    assert acquired[0]["generation"] == 2


def test_migration_from_pre_lease_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE oikonomia_runs (
            run_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            payload_json TEXT NOT NULL,
            fingerprint TEXT
        );
        """
    )
    payload = {
        "id": "run-legacy",
        "model_id": "m1",
        "status": "running",
        "trigger": {
            "trigger_type": "manual",
            "as_of": datetime.now(UTC).isoformat(),
        },
        "input_snapshot": {
            "snapshot_id": "snap-legacy",
            "as_of": datetime.now(UTC).isoformat(),
        },
        "fingerprint": "fp-legacy",
        "requested_by": "old-worker",
        "created_at": datetime.now(UTC).isoformat(),
    }
    conn.execute(
        """
        INSERT INTO oikonomia_runs (
            run_id, model_id, status, created_at, fingerprint, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "run-legacy",
            "m1",
            "running",
            datetime.now(UTC).isoformat(),
            "fp-legacy",
            json.dumps(payload),
        ),
    )
    conn.commit()
    conn.close()

    store = OikonomiaStore(db_path, clock=FileClock(tmp_path / "clock"))
    loaded = store.get_run("run-legacy")
    assert loaded is not None
    assert loaded.status == RunStatus.RUNNING
    assert loaded.lease_owner is None
    claimed = store.claim_run("run-legacy", "new-worker", LEASE)
    assert claimed.kind == ClaimKind.UNCLAIMABLE
    recovered = store.recover_legacy_run("run-legacy", "operator", LEASE)
    assert recovered.lease_owner == "operator"
    nxt = store.claim_run("run-legacy", "new-worker", LEASE)
    assert nxt.kind == ClaimKind.ACQUIRED
    assert nxt.run.lease_generation == recovered.lease_generation + 1


def test_fingerprint_create_after_crash_does_not_duplicate(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, InstantAdapter(tmp_path / "calls"))
    first = runtime.create_run("m1", _trigger("fp-crash"), fingerprint="fp-crash")
    again = runtime.create_run("m1", _trigger("fp-crash"), fingerprint="fp-crash")
    assert again.id == first.id
    assert len(runtime.store.list_runs()) == 1


def test_adapter_failure_is_terminal_and_not_retried(tmp_path: Path) -> None:
    counter = tmp_path / "calls"
    runtime = _runtime(tmp_path, BoomAdapter(counter), adapter_id="boom")
    queued = runtime.create_run("m1", _trigger("fp-fail"), fingerprint="fp-fail")
    failed = runtime.execute_run(queued.id)
    assert failed.status == RunStatus.FAILED
    replay = runtime.execute_run(queued.id)
    assert replay.status == RunStatus.FAILED
    assert counter.read_text() == "1"


def test_complete_without_lease_credentials_is_rejected(tmp_path: Path) -> None:
    from sophia_oikonomia.core.types import CompleteRunRequest, OwnershipError

    runtime = _runtime(tmp_path, InstantAdapter(tmp_path / "calls"))
    queued = runtime.create_run("m1", _trigger("fp-http"), fingerprint="fp-http")
    with pytest.raises(OwnershipError):
        runtime.complete_run(
            queued.id,
            CompleteRunRequest(status=RunStatus.SUCCEEDED, output_summary={"x": 1}),
        )
