from datetime import UTC, datetime
from pathlib import Path

from sophia_oikonomia.adapters import HYPOTHESIS_TEST_ADAPTER_ID, HypothesisTestAdapter
from sophia_oikonomia.adapters.registry import AdapterRegistry
from sophia_oikonomia.core.runtime import OikonomiaRuntime
from sophia_oikonomia.core.store import OikonomiaStore
from sophia_oikonomia.core.types import (
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


def test_execute_resumes_running_run(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    queued = runtime.create_run(
        "episto-granger-predictive",
        _trigger("fp-running"),
        fingerprint="fp-running",
    )
    running = queued.model_copy(update={"status": RunStatus.RUNNING})
    runtime.store.save_run(running)
    done = runtime.execute_run(queued.id)
    assert done.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}
    assert runtime.execute_run(queued.id).id == done.id


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
