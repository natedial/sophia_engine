from datetime import UTC, datetime, timedelta
from pathlib import Path

from sophia_oikonomia.adapters import HYPOTHESIS_TEST_ADAPTER_ID, HypothesisTestAdapter
from sophia_oikonomia.adapters.registry import AdapterRegistry
from sophia_oikonomia.core.clock import FileClock
from sophia_oikonomia.core.runtime import OikonomiaRuntime
from sophia_oikonomia.core.store import OikonomiaStore
from sophia_oikonomia.core.types import (
    ClaimKind,
    ExecutionSpec,
    ModelDefinition,
    ModelFamily,
    ModelState,
    ModelTrigger,
    RunStatus,
    TriggerType,
)


def _runtime(tmp_path: Path) -> OikonomiaRuntime:
    adapters = AdapterRegistry()
    adapters.register(HYPOTHESIS_TEST_ADAPTER_ID, HypothesisTestAdapter())
    runtime = OikonomiaRuntime(store=OikonomiaStore(tmp_path / "oikonomia.db"), adapters=adapters)
    runtime.register_model(
        ModelDefinition(
            id="episto-granger-predictive",
            name="Episto Granger predictive test",
            family=ModelFamily.MACRO,
            owner="episto",
            state=ModelState.RESEARCH,
            execution=ExecutionSpec(adapter_id=HYPOTHESIS_TEST_ADAPTER_ID),
            metadata={"epistemic_support": False},
        )
    )
    return runtime


def _trigger(fingerprint: str) -> ModelTrigger:
    return ModelTrigger(
        trigger_type=TriggerType.HYPOTHESIS,
        as_of=datetime.now(UTC),
        model_ids=["episto-granger-predictive"],
        payload={
            "fingerprint": fingerprint,
            "method": "granger_predictive",
            "question_type": "predictive",
            "input": {
                "vintage": "v1",
                "source_series": "x",
                "target_series": "y",
                "source_observations": [
                    {"date": "2020-01-01", "value": float(i)} for i in range(40)
                ],
                "target_observations": [
                    {"date": "2020-01-01", "value": float(i) + 0.1} for i in range(40)
                ],
            },
        },
    )


def test_fingerprint_deduplicates_runs(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    trigger = _trigger("fp-same")
    first = runtime.create_run(
        "episto-granger-predictive", trigger, fingerprint="fp-same"
    )
    second = runtime.create_run(
        "episto-granger-predictive", trigger, fingerprint="fp-same"
    )
    assert first.id == second.id
    assert first.status == RunStatus.QUEUED


def test_execute_is_idempotent_after_success(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    trigger = _trigger("fp-run")
    queued = runtime.create_run(
        "episto-granger-predictive", trigger, fingerprint="fp-run"
    )
    done = runtime.execute_run(queued.id)
    again = runtime.execute_run(queued.id)
    assert done.id == again.id
    assert done.status == again.status
    assert again.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}


def test_fingerprint_conflict_does_not_replace_existing(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    first = runtime.create_run(
        "episto-granger-predictive", _trigger("fp-keep"), fingerprint="fp-keep"
    )
    again = runtime.create_run(
        "episto-granger-predictive", _trigger("fp-keep"), fingerprint="fp-keep"
    )
    assert again.id == first.id
    assert len(runtime.store.list_runs()) == 1


def test_legacy_running_without_lease_is_not_auto_reclaimed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    queued = runtime.create_run(
        "episto-granger-predictive",
        _trigger("fp-running"),
        fingerprint="fp-running",
    )
    import sqlite3

    with sqlite3.connect(runtime.store.db_path) as conn:
        conn.execute(
            "UPDATE oikonomia_runs SET status = ? WHERE run_id = ?",
            (RunStatus.RUNNING.value, queued.id),
        )
        payload = conn.execute(
            "SELECT payload_json FROM oikonomia_runs WHERE run_id = ?",
            (queued.id,),
        ).fetchone()[0]
        import json

        data = json.loads(payload)
        data["status"] = RunStatus.RUNNING.value
        conn.execute(
            "UPDATE oikonomia_runs SET payload_json = ? WHERE run_id = ?",
            (json.dumps(data), queued.id),
        )
    try:
        runtime.execute_run(queued.id)
        raise AssertionError("expected unclaimable legacy RUNNING")
    except ValueError as exc:
        assert "lease metadata" in str(exc)
    claimed = runtime.store.claim_run(
        queued.id, "worker-b", timedelta(seconds=60)
    )
    assert claimed.kind == ClaimKind.UNCLAIMABLE
    recovered = runtime.recover_legacy_running(queued.id, owner="operator")
    assert recovered.lease_owner == "operator"
    done = runtime.execute_run(queued.id)
    assert done.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}


def test_valid_lease_is_not_resumed_by_another_worker(tmp_path: Path) -> None:
    clock = FileClock(tmp_path / "clock")
    store = OikonomiaStore(tmp_path / "oikonomia.db", clock=clock)
    adapters = AdapterRegistry()
    adapters.register(HYPOTHESIS_TEST_ADAPTER_ID, HypothesisTestAdapter())
    runtime = OikonomiaRuntime(
        store=store,
        adapters=adapters,
        lease_duration=timedelta(seconds=60),
        heartbeat_interval=timedelta(days=1),
    )
    runtime.register_model(
        ModelDefinition(
            id="episto-granger-predictive",
            name="Episto Granger predictive test",
            family=ModelFamily.MACRO,
            owner="episto",
            state=ModelState.RESEARCH,
            execution=ExecutionSpec(adapter_id=HYPOTHESIS_TEST_ADAPTER_ID),
        )
    )
    queued = runtime.create_run(
        "episto-granger-predictive",
        _trigger("fp-held"),
        fingerprint="fp-held",
    )
    first = runtime.store.claim_run(queued.id, "worker-a", timedelta(seconds=60))
    assert first.kind == ClaimKind.ACQUIRED
    pending = runtime.execute_run(queued.id)
    assert pending.status == RunStatus.RUNNING
    assert pending.lease_owner == "worker-a"


def test_successful_test_is_not_published(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    trigger = _trigger("fp-pub")
    queued = runtime.create_run(
        "episto-granger-predictive", trigger, fingerprint="fp-pub"
    )
    runtime.execute_run(queued.id)
    assert runtime.get_latest_publication("episto-granger-predictive") is None
    model = runtime.get_model("episto-granger-predictive")
    assert model is not None
    assert model.state == ModelState.RESEARCH
