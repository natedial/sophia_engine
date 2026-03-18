"""Runtime logic for Oikonomia Phase 1."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ..adapters import AdapterRegistry
from ..clients import ScrivenerClient
from ..config import settings
from .store import OikonomiaStore
from .types import (
    CompleteRunRequest,
    GateStatus,
    InputSnapshotRef,
    ModelDefinition,
    ModelExecutionResult,
    ModelRun,
    ModelState,
    ModelTrigger,
    PromoteModelRequest,
    PromotionGate,
    PromotionReview,
    PublishProjectionRequest,
    PublishedProjection,
    PublicationState,
    ReviewModelRequest,
    RunPlan,
    RunPlanItem,
    RunStatus,
    TriggerExecutionResult,
    TriggerType,
)


class OikonomiaRuntime:
    """Stateful orchestration runtime for economic model lifecycle."""

    def __init__(
        self,
        store: OikonomiaStore | None = None,
        *,
        adapters: AdapterRegistry | None = None,
        scrivener: ScrivenerClient | None = None,
    ) -> None:
        self.store = store or OikonomiaStore()
        self.adapters = adapters or AdapterRegistry()
        self.scrivener = scrivener or ScrivenerClient(
            base_url=settings.scrivener_url,
            timeout_sec=settings.request_timeout_sec,
        )

    def register_model(self, definition: ModelDefinition) -> ModelDefinition:
        definition = definition.model_copy(update={"updated_at": datetime.now(UTC)})
        return self.store.save_model(definition)

    def list_models(self) -> list[ModelDefinition]:
        return self.store.list_models()

    def get_model(self, model_id: str) -> ModelDefinition | None:
        return self.store.get_model(model_id)

    def get_current_champion(self, production_slot: str) -> ModelDefinition | None:
        return self.store.get_current_champion(production_slot)

    def get_run(self, run_id: str) -> ModelRun | None:
        return self.store.get_run(run_id)

    def list_reviews(self, model_id: str) -> list[PromotionReview]:
        return self.store.list_reviews(model_id)

    def list_publications(self) -> list[PublishedProjection]:
        return self.store.list_publications()

    def get_latest_publication(self, model_id: str) -> PublishedProjection | None:
        return self.store.get_latest_publication(model_id)

    def get_latest_publication_for_slot(self, production_slot: str) -> PublishedProjection | None:
        champion = self.get_current_champion(production_slot)
        if champion is None:
            return None
        return self.get_latest_publication(champion.id)

    def plan_runs(self, trigger: ModelTrigger) -> RunPlan:
        impacted: list[RunPlanItem] = []
        requested_ids = set(trigger.model_ids)

        for definition in self.store.list_models():
            if not self._is_plannable(definition, trigger, requested_ids):
                continue
            if requested_ids and definition.id not in requested_ids:
                continue

            matches = self._match_trigger(definition, trigger)
            if matches:
                impacted.append(
                    RunPlanItem(
                        model_id=definition.id,
                        trigger_reason=self._trigger_reason(trigger),
                        source_matches=matches,
                    )
                )

        return RunPlan(trigger=trigger, impacted_models=impacted)

    def create_run(
        self,
        model_id: str,
        trigger: ModelTrigger,
        requested_by: str = "system",
    ) -> ModelRun:
        definition = self.store.get_model(model_id)
        if definition is None:
            raise ValueError(f"Unknown model: {model_id}")

        snapshot = self._build_snapshot(definition, trigger)

        run = ModelRun(
            id=f"run-{uuid4().hex[:12]}",
            model_id=model_id,
            trigger=trigger,
            input_snapshot=snapshot,
            requested_by=requested_by,
        )
        return self.store.save_run(run)

    def submit_review(self, model_id: str, request: ReviewModelRequest) -> PromotionReview:
        definition = self.store.get_model(model_id)
        if definition is None:
            raise ValueError(f"Unknown model: {model_id}")

        review = PromotionReview(
            id=f"review-{uuid4().hex[:12]}",
            model_id=model_id,
            requested_state=request.requested_state,
            gate_results=request.gate_results,
            reviewer=request.reviewer,
            notes=request.notes,
        )
        self.store.save_review(review)
        return review

    def promote_model(self, model_id: str, request: PromoteModelRequest) -> ModelDefinition:
        definition = self.store.get_model(model_id)
        if definition is None:
            raise ValueError(f"Unknown model: {model_id}")

        self._assert_promotion_allowed(definition, request.target_state)
        review = self.store.get_latest_review(model_id)
        if review is None or review.requested_state != request.target_state:
            raise ValueError(
                f"Model '{model_id}' has no matching review for promotion to {request.target_state.value}"
            )

        gate_map = {result.gate: result.status for result in review.gate_results}
        for gate in self._required_gates(request.target_state):
            if gate_map.get(gate) not in {GateStatus.PASSED, GateStatus.WAIVED}:
                raise ValueError(
                    f"Model '{model_id}' failed promotion gate '{gate.value}' for {request.target_state.value}"
                )

        updates: dict[str, object] = {
            "state": request.target_state,
            "updated_at": datetime.now(UTC),
        }
        promotion = definition.promotion.model_copy()

        if request.target_state == ModelState.CHAMPION:
            if not definition.production_slot:
                raise ValueError(f"Model '{model_id}' needs a production_slot before champion promotion")

            prior_champion = self.store.get_current_champion(definition.production_slot)
            if prior_champion and prior_champion.id != model_id:
                demoted = prior_champion.model_copy(
                    update={"state": ModelState.SHADOW, "updated_at": datetime.now(UTC)}
                )
                self.store.save_model(demoted)
                promotion = promotion.model_copy(update={"rollback_model_id": prior_champion.id})

        updates["promotion"] = promotion
        promoted = definition.model_copy(update=updates)
        return self.store.save_model(promoted)

    def create_and_execute_run(
        self,
        model_id: str,
        trigger: ModelTrigger,
        requested_by: str = "system",
    ) -> ModelRun:
        """Create and immediately execute a run."""
        run = self.create_run(model_id=model_id, trigger=trigger, requested_by=requested_by)
        return self.execute_run(run.id)

    def execute_run(self, run_id: str) -> ModelRun:
        """Execute an existing run through its registered adapter."""
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")

        definition = self.store.get_model(run.model_id)
        if definition is None:
            raise ValueError(f"Unknown model: {run.model_id}")

        adapter = self.adapters.get(definition.execution.adapter_id)
        if adapter is None:
            raise ValueError(
                f"No adapter registered for adapter_id '{definition.execution.adapter_id}'"
            )

        running = run.model_copy(
            update={
                "status": RunStatus.RUNNING,
                "started_at": datetime.now(UTC),
                "error": None,
            }
        )
        self.store.save_run(running)

        try:
            result = adapter.execute(definition, running)
        except Exception as exc:
            result = ModelExecutionResult(
                status=RunStatus.FAILED,
                output_summary={
                    "status": "error",
                    "exception_type": exc.__class__.__name__,
                    "message": str(exc),
                },
                raw_output={},
                insights=[],
                quality_score=None,
                error=str(exc),
            )

        return self.complete_run(
            run_id,
            CompleteRunRequest(
                status=result.status,
                output_summary=result.output_summary,
                raw_output=result.raw_output,
                insights=result.insights,
                quality_score=result.quality_score,
                error=result.error,
            ),
        )

    def execute_trigger(
        self,
        trigger: ModelTrigger,
        *,
        requested_by: str = "system",
    ) -> TriggerExecutionResult:
        """Plan and execute all impacted model runs for a trigger."""
        plan = self.plan_runs(trigger)
        runs = [
            self.create_and_execute_run(item.model_id, trigger, requested_by=requested_by)
            for item in plan.impacted_models
        ]
        return TriggerExecutionResult(plan=plan, runs=runs)

    def complete_run(self, run_id: str, request: CompleteRunRequest) -> ModelRun:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")

        if request.status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            raise ValueError("Run completion must end in succeeded or failed status")

        updated = run.model_copy(
            update={
                "status": request.status,
                "completed_at": datetime.now(UTC),
                "raw_output": request.raw_output,
                "output_summary": request.output_summary,
                "insights": request.insights,
                "quality_score": request.quality_score,
                "error": request.error,
            }
        )
        return self.store.save_run(updated)

    def publish_projection(self, request: PublishProjectionRequest) -> PublishedProjection:
        run = self.store.get_run(request.run_id)
        if run is None:
            raise ValueError(f"Unknown run: {request.run_id}")
        if run.status != RunStatus.SUCCEEDED:
            raise ValueError("Only successful runs can be published")
        definition = self.store.get_model(run.model_id)
        if definition is None:
            raise ValueError(f"Unknown model: {run.model_id}")
        if definition.state not in {ModelState.CHAMPION, ModelState.ACTIVE}:
            raise ValueError("Only champion models can publish projections")

        publication = PublishedProjection(
            id=f"pub-{uuid4().hex[:12]}",
            model_id=run.model_id,
            run_id=run.id,
            as_of=run.input_snapshot.as_of,
            state=PublicationState.PUBLISHED,
            summary=request.summary or run.output_summary,
            insights=request.insights or run.insights,
            quality_score=request.quality_score
            if request.quality_score is not None
            else run.quality_score,
        )

        updated_run = run.model_copy(update={"status": RunStatus.PUBLISHED})
        self.store.save_run(updated_run)
        return self.store.save_publication(publication)

    def stats(self) -> dict[str, int]:
        raw = self.store.stats()
        return {
            "models": int(raw["models"]),
            "runs": int(raw["runs"]),
            "reviews": int(raw["reviews"]),
            "publications": int(raw["publications"]),
        }

    def _is_plannable(
        self,
        definition: ModelDefinition,
        trigger: ModelTrigger,
        requested_ids: set[str],
    ) -> bool:
        if requested_ids:
            return definition.state not in {ModelState.RETIRED, ModelState.ARCHIVED}
        if definition.state in {ModelState.SHADOW, ModelState.CHAMPION, ModelState.ACTIVE}:
            return True
        return False

    def _assert_promotion_allowed(self, definition: ModelDefinition, target_state: ModelState) -> None:
        if target_state in {ModelState.RESEARCH, ModelState.ARCHIVED}:
            raise ValueError(f"Promotion target '{target_state.value}' is not supported")
        if definition.state == ModelState.RETIRED and target_state != ModelState.SHADOW:
            raise ValueError("Retired models may only be revived into shadow first")

    def _required_gates(self, target_state: ModelState) -> set[PromotionGate]:
        if target_state == ModelState.CANDIDATE:
            return {PromotionGate.CONTRACT_TESTS, PromotionGate.OPS_CHECKS}
        if target_state == ModelState.SHADOW:
            return {
                PromotionGate.CONTRACT_TESTS,
                PromotionGate.EVAL_REPLAY,
                PromotionGate.OPS_CHECKS,
            }
        if target_state == ModelState.CHAMPION:
            return {
                PromotionGate.CONTRACT_TESTS,
                PromotionGate.EVAL_REPLAY,
                PromotionGate.SHADOW_RUNS,
                PromotionGate.OPS_CHECKS,
            }
        return set()

    def _match_trigger(self, definition: ModelDefinition, trigger: ModelTrigger) -> list[str]:
        if trigger.trigger_type == TriggerType.MANUAL:
            return ["manual"]

        if trigger.trigger_type == TriggerType.SCHEDULED:
            if definition.cadence.cron:
                return [f"cron:{definition.cadence.cron}"]
            return []

        matches: list[str] = []
        for dependency in definition.dependencies:
            if trigger.source and dependency.source != trigger.source:
                continue
            if trigger.release_name and dependency.release_name == trigger.release_name:
                provider = dependency.provider or "default"
                matches.append(f"{dependency.source}:{provider}:{dependency.release_name}")
                continue
            if trigger.series_ids and dependency.series_id in set(trigger.series_ids):
                provider = dependency.provider or "default"
                matches.append(f"{dependency.source}:{provider}:{dependency.series_id}")

        return matches

    def _trigger_reason(self, trigger: ModelTrigger) -> str:
        if trigger.reason:
            return trigger.reason
        return trigger.trigger_type.value

    def _build_source_refs(
        self,
        definition: ModelDefinition,
        trigger: ModelTrigger,
    ) -> list[str]:
        refs: list[str] = []
        for dependency in definition.dependencies:
            provider = dependency.provider or "default"
            if dependency.series_id:
                refs.append(f"{dependency.source}:{provider}:{dependency.series_id}")
            elif dependency.release_name:
                refs.append(f"{dependency.source}:{provider}:{dependency.release_name}")

        if not refs:
            refs.append(trigger.trigger_type.value)

        return refs

    def _build_snapshot(
        self,
        definition: ModelDefinition,
        trigger: ModelTrigger,
    ) -> InputSnapshotRef:
        adapter = self.adapters.get(definition.execution.adapter_id)
        if adapter is None:
            source_refs = self._build_source_refs(definition, trigger)
            return InputSnapshotRef(
                snapshot_id=f"snap-{uuid4().hex[:12]}",
                as_of=trigger.as_of,
                source_refs=source_refs,
                metadata={
                    "model_id": definition.id,
                    "trigger_type": trigger.trigger_type.value,
                    "adapter_id": definition.execution.adapter_id,
                },
            )

        snapshot = adapter.build_input_snapshot(definition, trigger)
        return snapshot.model_copy(
            update={
                "metadata": {
                    **snapshot.metadata,
                    "model_id": definition.id,
                    "trigger_type": trigger.trigger_type.value,
                    "adapter_id": definition.execution.adapter_id,
                }
            }
        )
