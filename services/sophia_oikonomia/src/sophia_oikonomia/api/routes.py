"""API routes for Sophia Oikonomia."""

from fastapi import APIRouter, HTTPException

from .. import __version__
from ..core.runtime import OikonomiaRuntime
from ..core.types import (
    CompleteRunRequest,
    ModelDefinition,
    ModelRun,
    ModelTrigger,
    PromoteModelRequest,
    PublishProjectionRequest,
    PublishedProjection,
    PromotionReview,
    ReviewModelRequest,
    RunPlan,
    TriggerExecutionResult,
)


def build_router(runtime: OikonomiaRuntime) -> APIRouter:
    """Create a router bound to the provided runtime."""

    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "healthy",
            "service": "sophia_oikonomia",
            "version": __version__,
            "stats": runtime.stats(),
        }

    @router.get("/v1/models", response_model=list[ModelDefinition])
    async def list_models() -> list[ModelDefinition]:
        return runtime.list_models()

    @router.get("/v1/models/{model_id}", response_model=ModelDefinition)
    async def get_model(model_id: str) -> ModelDefinition:
        model = runtime.get_model(model_id)
        if model is None:
            raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
        return model

    @router.get("/v1/slots/{production_slot}/champion", response_model=ModelDefinition)
    async def get_slot_champion(production_slot: str) -> ModelDefinition:
        model = runtime.get_current_champion(production_slot)
        if model is None:
            raise HTTPException(status_code=404, detail=f"No champion for slot: {production_slot}")
        return model

    @router.post("/v1/models", response_model=ModelDefinition, status_code=201)
    async def register_model(definition: ModelDefinition) -> ModelDefinition:
        return runtime.register_model(definition)

    @router.get("/v1/models/{model_id}/reviews", response_model=list[PromotionReview])
    async def list_reviews(model_id: str) -> list[PromotionReview]:
        return runtime.list_reviews(model_id)

    @router.post("/v1/models/{model_id}/review", response_model=PromotionReview, status_code=201)
    async def submit_review(model_id: str, request: ReviewModelRequest) -> PromotionReview:
        try:
            return runtime.submit_review(model_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/v1/models/{model_id}/promote", response_model=ModelDefinition)
    async def promote_model(model_id: str, request: PromoteModelRequest) -> ModelDefinition:
        try:
            return runtime.promote_model(model_id, request)
        except ValueError as exc:
            status_code = 404 if "Unknown model" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @router.post("/v1/triggers/plan", response_model=RunPlan)
    async def plan_trigger(trigger: ModelTrigger) -> RunPlan:
        return runtime.plan_runs(trigger)

    @router.post("/v1/runs", response_model=ModelRun, status_code=201)
    async def create_run(payload: dict[str, object]) -> ModelRun:
        model_id = payload.get("model_id")
        trigger = payload.get("trigger")
        requested_by = payload.get("requested_by", "system")

        if not isinstance(model_id, str):
            raise HTTPException(status_code=422, detail="model_id is required")
        if not isinstance(trigger, dict):
            raise HTTPException(status_code=422, detail="trigger is required")

        try:
            parsed_trigger = ModelTrigger.model_validate(trigger)
            return runtime.create_run(model_id=model_id, trigger=parsed_trigger, requested_by=str(requested_by))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/v1/runs/execute", response_model=ModelRun, status_code=201)
    async def create_and_execute_run(payload: dict[str, object]) -> ModelRun:
        model_id = payload.get("model_id")
        trigger = payload.get("trigger")
        requested_by = payload.get("requested_by", "system")

        if not isinstance(model_id, str):
            raise HTTPException(status_code=422, detail="model_id is required")
        if not isinstance(trigger, dict):
            raise HTTPException(status_code=422, detail="trigger is required")

        try:
            parsed_trigger = ModelTrigger.model_validate(trigger)
            return runtime.create_and_execute_run(
                model_id=model_id,
                trigger=parsed_trigger,
                requested_by=str(requested_by),
            )
        except ValueError as exc:
            status_code = 404 if "Unknown" in str(exc) or "No adapter" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @router.get("/v1/runs/{run_id}", response_model=ModelRun)
    async def get_run(run_id: str) -> ModelRun:
        run = runtime.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return run

    @router.post("/v1/runs/{run_id}/complete", response_model=ModelRun)
    async def complete_run(run_id: str, request: CompleteRunRequest) -> ModelRun:
        try:
            return runtime.complete_run(run_id, request)
        except ValueError as exc:
            status_code = 404 if "Unknown run" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @router.post("/v1/runs/{run_id}/execute", response_model=ModelRun)
    async def execute_run(run_id: str) -> ModelRun:
        try:
            return runtime.execute_run(run_id)
        except ValueError as exc:
            status_code = 404 if "Unknown" in str(exc) or "No adapter" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @router.post("/v1/triggers/execute", response_model=TriggerExecutionResult)
    async def execute_trigger(payload: dict[str, object]) -> TriggerExecutionResult:
        trigger = payload.get("trigger")
        requested_by = payload.get("requested_by", "system")
        if not isinstance(trigger, dict):
            raise HTTPException(status_code=422, detail="trigger is required")

        parsed_trigger = ModelTrigger.model_validate(trigger)
        return runtime.execute_trigger(parsed_trigger, requested_by=str(requested_by))

    @router.get("/v1/publications", response_model=list[PublishedProjection])
    async def list_publications() -> list[PublishedProjection]:
        return runtime.list_publications()

    @router.get("/v1/publications/latest/{model_id}", response_model=PublishedProjection)
    async def get_latest_publication(model_id: str) -> PublishedProjection:
        publication = runtime.get_latest_publication(model_id)
        if publication is None:
            raise HTTPException(status_code=404, detail=f"No publication for model: {model_id}")
        return publication

    @router.get("/v1/publications/latest/slot/{production_slot}", response_model=PublishedProjection)
    async def get_latest_publication_for_slot(production_slot: str) -> PublishedProjection:
        publication = runtime.get_latest_publication_for_slot(production_slot)
        if publication is None:
            raise HTTPException(
                status_code=404,
                detail=f"No publication for production slot: {production_slot}",
            )
        return publication

    @router.post("/v1/publications", response_model=PublishedProjection, status_code=201)
    async def publish_projection(request: PublishProjectionRequest) -> PublishedProjection:
        try:
            return runtime.publish_projection(request)
        except ValueError as exc:
            status_code = 404 if "Unknown run" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return router
