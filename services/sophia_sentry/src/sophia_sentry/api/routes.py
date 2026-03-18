"""FastAPI routes for Sophia Sentry."""

from fastapi import APIRouter, HTTPException, status

from sophia_sentry.core.runtime import SentryRuntime
from sophia_sentry.core.types import PublicationUpdatePayload, WatchDefinition, WatchEvaluationRequest


def build_router(runtime: SentryRuntime) -> APIRouter:
    """Create an API router bound to the given runtime."""
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": "sophia_sentry"}

    @router.get("/v1/watches")
    def list_watches() -> list[dict]:
        return [watch.model_dump(mode="json") for watch in runtime.list_watches()]

    @router.get("/v1/watches/{watch_id}")
    def get_watch(watch_id: str) -> dict:
        watch = runtime.get_watch(watch_id)
        if watch is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="watch_not_found")
        return watch.model_dump(mode="json")

    @router.post("/v1/watches", status_code=status.HTTP_201_CREATED)
    def create_watch(payload: WatchDefinition) -> dict:
        watch = runtime.register_watch(payload)
        return watch.model_dump(mode="json")

    @router.post("/v1/watches/{watch_id}/evaluate")
    def evaluate_watch(watch_id: str, payload: WatchEvaluationRequest) -> dict:
        try:
            result = runtime.evaluate_watch(watch_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="watch_not_found",
            ) from exc
        return result.model_dump(mode="json")

    @router.post("/v1/evaluate")
    def evaluate(payload: WatchEvaluationRequest) -> list[dict]:
        return [result.model_dump(mode="json") for result in runtime.evaluate(payload)]

    @router.post("/v1/integrations/oikonomia/publications")
    def handle_oikonomia_publication(payload: PublicationUpdatePayload) -> list[dict]:
        return [
            result.model_dump(mode="json")
            for result in runtime.handle_publication_update(payload)
        ]

    @router.get("/v1/events")
    def list_events(watch_id: str | None = None) -> list[dict]:
        return [event.model_dump(mode="json") for event in runtime.list_events(watch_id=watch_id)]

    return router
