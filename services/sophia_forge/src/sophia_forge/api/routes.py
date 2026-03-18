"""HTTP routes for the forge runtime service."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from sophia_forge.core.runtime import ForgeRuntime
from sophia_forge.evals import EvalCaseExportRequest, EvalCaseReviewRequest, EvalReplayRequest
from sophia_forge_protocol.run_models import CapabilityHandoffUpdate, RunRequest


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

    @router.get("/runs/{run_id}/request")
    async def get_run_request(run_id: str):
        try:
            return runtime.get_run_request(run_id).model_dump(mode="json")
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

    @router.get("/metrics/summary")
    async def get_metrics_summary():
        return runtime.get_metrics_summary().model_dump(mode="json")

    @router.get("/capabilities")
    async def list_capability_handoffs():
        return {
            "entries": [
                item.model_dump(mode="json") for item in runtime.list_capability_handoffs()
            ]
        }

    @router.post("/capabilities")
    async def upsert_capability_handoffs(request: CapabilityHandoffUpdate):
        return {
            "entries": [
                item.model_dump(mode="json")
                for item in runtime.upsert_capability_handoffs(request)
            ]
        }

    @router.get("/retention/summary")
    async def get_retention_summary():
        return runtime.inspect_retention().model_dump(mode="json")

    @router.post("/retention/cleanup")
    async def cleanup_retention():
        return runtime.cleanup_retention().model_dump(mode="json")

    @router.post("/evals/replay")
    async def replay_eval_corpus(request: EvalReplayRequest):
        summary = await runtime.run_eval_corpus(
            corpus_dir=None if request.corpus_dir is None else Path(request.corpus_dir),
            backend_override=request.backend_override,
        )
        return summary.model_dump(mode="json")

    @router.get("/evals")
    async def list_eval_runs():
        return {"eval_runs": [item.model_dump(mode="json") for item in runtime.list_eval_runs()]}

    @router.post("/evals/export/{run_id}")
    async def export_eval_case(run_id: str, request: EvalCaseExportRequest):
        try:
            record = runtime.export_eval_case_from_run(
                run_id,
                output_dir=None if request.output_dir is None else Path(request.output_dir),
                case_id=request.case_id,
                name=request.name,
                description=request.description,
                tags=request.tags,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return record.model_dump(mode="json")

    @router.get("/evals/cases")
    async def list_eval_cases(
        corpus_dir: str | None = None,
        status: str | None = None,
    ):
        statuses = None if status is None else (status,)
        cases = runtime.list_curated_eval_cases(
            corpus_dir=None if corpus_dir is None else Path(corpus_dir),
            statuses=statuses,
        )
        return {"cases": [case.model_dump(mode="json") for case in cases]}

    @router.post("/evals/cases/{case_id}/review")
    async def review_eval_case(case_id: str, request: EvalCaseReviewRequest):
        try:
            case = runtime.review_eval_case(
                case_id,
                corpus_dir=Path(request.corpus_dir),
                status=request.status,
                curation_notes=request.curation_notes,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="eval case not found") from exc
        return case.model_dump(mode="json")

    @router.get("/evals/{eval_run_id}")
    async def get_eval_run(eval_run_id: str):
        try:
            return runtime.get_eval_run(eval_run_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="eval run not found") from exc

    @router.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        try:
            runtime.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return (await runtime.cancel_run(run_id)).model_dump(mode="json")

    return router
