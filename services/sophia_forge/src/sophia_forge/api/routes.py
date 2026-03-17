"""HTTP routes for the forge runtime service."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from sophia_forge.core.runtime import ForgeRuntime
from sophia_forge_protocol.run_models import RunRequest


def build_router(runtime: ForgeRuntime) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.post("/runs")
    async def create_run(request: RunRequest):
        return (await runtime.submit_run(request)).model_dump(mode="json")

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str):
        try:
            return runtime.get_run(run_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @router.get("/runs/{run_id}/events")
    async def get_run_events(run_id: str):
        try:
            runtime.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {
            "run_id": run_id,
            "events": [event.model_dump(mode="json") for event in runtime.get_events(run_id)],
        }

    @router.get("/runs/{run_id}/artifacts")
    async def get_run_artifacts(run_id: str):
        try:
            runtime.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {
            "run_id": run_id,
            "artifacts": [
                artifact.model_dump(mode="json") for artifact in runtime.get_artifacts(run_id)
            ],
        }

    @router.get("/runs/{run_id}/verification")
    async def get_run_verification(run_id: str):
        try:
            runtime.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {
            "run_id": run_id,
            "verification_results": [
                result.model_dump(mode="json") for result in runtime.get_verification_results(run_id)
            ],
        }

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        try:
            runtime.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return (await runtime.cancel_run(run_id)).model_dump(mode="json")

    return router
