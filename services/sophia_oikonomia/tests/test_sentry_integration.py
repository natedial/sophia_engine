"""Tests for Oikonomia -> Sentry publication notifications."""

from datetime import UTC, datetime

from sophia_oikonomia.adapters.base import ModelAdapter
from sophia_oikonomia.adapters.registry import AdapterRegistry
from sophia_oikonomia.core.runtime import OikonomiaRuntime
from sophia_oikonomia.core.store import OikonomiaStore
from sophia_oikonomia.core.types import (
    AnalysisSpec,
    CadencePolicy,
    CompleteRunRequest,
    ExecutionSpec,
    InputSnapshotRef,
    ModelDefinition,
    ModelExecutionResult,
    ModelFamily,
    ModelRun,
    ModelState,
    ModelTrigger,
    PublishProjectionRequest,
    RunStatus,
    TriggerType,
)


class _NoopAdapter(ModelAdapter):
    def build_input_snapshot(
        self,
        definition: ModelDefinition,
        trigger: ModelTrigger,
    ) -> InputSnapshotRef:
        return InputSnapshotRef(snapshot_id="snap-1", as_of=trigger.as_of)

    def execute(
        self,
        definition: ModelDefinition,
        run: ModelRun,
    ) -> ModelExecutionResult:
        return ModelExecutionResult(status=RunStatus.SUCCEEDED)


class _FakeSentryClient:
    def __init__(self) -> None:
        self.notifications: list[dict] = []

    def notify_publication(self, payload: dict) -> list[dict]:
        self.notifications.append(payload)
        return []


def test_publish_projection_notifies_sentry(tmp_path) -> None:
    store = OikonomiaStore(tmp_path / "oikonomia.db")
    sentry = _FakeSentryClient()
    adapters = AdapterRegistry()
    adapters.register("noop", _NoopAdapter())
    runtime = OikonomiaRuntime(store=store, adapters=adapters, sentry=sentry)

    definition = ModelDefinition(
        id="bistro-v1",
        name="Bistro",
        family=ModelFamily.MACRO,
        owner="macro",
        state=ModelState.CHAMPION,
        production_slot="macro_us_inflation",
        cadence=CadencePolicy(),
        execution=ExecutionSpec(adapter_id="noop"),
        analysis=AnalysisSpec(),
    )
    runtime.register_model(definition)

    trigger = ModelTrigger(
        trigger_type=TriggerType.MANUAL,
        as_of=datetime(2026, 3, 18, 15, 0, tzinfo=UTC),
    )
    run = runtime.create_run("bistro-v1", trigger, requested_by="tester")
    runtime.complete_run(
        run.id,
        CompleteRunRequest(
            status=RunStatus.SUCCEEDED,
            output_summary={"core_cpi_3m_annualized": 3.4},
            insights=["Inflation revised higher."],
            quality_score=0.8,
        ),
    )

    runtime.publish_projection(
        PublishProjectionRequest(
            run_id=run.id,
            summary={"core_cpi_3m_annualized": 3.4},
            insights=["Inflation revised higher."],
        )
    )

    assert len(sentry.notifications) == 1
    payload = sentry.notifications[0]
    assert payload["production_slot"] == "macro_us_inflation"
    assert payload["current_summary"]["core_cpi_3m_annualized"] == 3.4
