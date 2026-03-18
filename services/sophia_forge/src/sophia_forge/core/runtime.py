"""Top-level runtime facade for the forge service."""

from __future__ import annotations

import uuid
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge.core.artifacts import ArtifactManager
from sophia_forge.core.retention import RetentionManager
from sophia_forge.core.scheduler import ForgeExecutor, RuntimeScheduler
from sophia_forge.core.verification import VerificationRunner
from sophia_forge.evals import (
    EvalCaseExport,
    EvalCaseReviewRequest,
    EvalCaseStatus,
    export_eval_case_record,
    EvalReplayRunner,
    EvalRunSummary,
    default_corpus_dir,
    list_eval_cases,
    load_eval_cases,
    review_eval_case,
)
from sophia_forge.storage.run_store import ForgeRunStore
from sophia_forge_protocol.artifact_models import RunArtifact
from sophia_forge_protocol.event_models import RunEvent
from sophia_forge_protocol.run_models import (
    CapabilityHandoff,
    CapabilityHandoffUpdate,
    RetentionSummary,
    RunMetricsSummary,
    RunRequest,
    RunResult,
)
from sophia_forge_protocol.verification_models import VerificationResult


class ForgeRuntime:
    """Coordinates run submission, persistence, and background execution."""

    def __init__(
        self,
        *,
        settings: ForgeSettings | None = None,
        executor: ForgeExecutor | None = None,
    ) -> None:
        self.settings = settings or ForgeSettings()
        self.run_store = ForgeRunStore(self.settings.store_path)
        self.artifact_manager = ArtifactManager(self.settings)
        self.verification_runner = VerificationRunner(settings=self.settings)
        self.scheduler = RuntimeScheduler(
            run_store=self.run_store,
            artifact_manager=self.artifact_manager,
            verification_runner=self.verification_runner,
            executor=executor,
            max_concurrent_runs=self.settings.max_concurrent_runs,
        )
        self.retention_manager = RetentionManager(
            settings=self.settings,
            run_store=self.run_store,
            artifact_manager=self.artifact_manager,
        )
        self.eval_runner = EvalReplayRunner(
            executor=self.scheduler.executor,
            verification_runner=self.verification_runner,
        )

    async def submit_run(self, request: RunRequest) -> RunResult:
        run_id = request.run_id or f"forge_{uuid.uuid4().hex[:12]}"
        normalized = request.model_copy(update={"run_id": run_id})
        snapshot = self.run_store.create_run(normalized)
        self.run_store.append_event(
            RunEvent(
                run_id=run_id,
                sequence=1,
                event_type="run_queued",
                timestamp=_utc_now(),
                payload={"backend": normalized.backend, "client_name": normalized.client_name},
            )
        )
        await self.scheduler.enqueue(normalized)
        return snapshot

    def get_run(self, run_id: str) -> RunResult:
        return self.run_store.get_run(run_id)

    def get_run_request(self, run_id: str) -> RunRequest:
        return self.run_store.get_run_request(run_id)

    def get_events(self, run_id: str) -> tuple[RunEvent, ...]:
        return self.run_store.list_events(run_id)

    def get_artifacts(self, run_id: str) -> tuple[RunArtifact, ...]:
        return self.run_store.list_artifacts(run_id)

    def get_verification_results(self, run_id: str) -> tuple[VerificationResult, ...]:
        return self.run_store.list_verification_results(run_id)

    def get_metrics_summary(self) -> RunMetricsSummary:
        return self.run_store.summarize_metrics()

    def list_capability_handoffs(self) -> tuple[CapabilityHandoff, ...]:
        return self.run_store.list_capability_handoffs()

    def upsert_capability_handoffs(
        self,
        update: CapabilityHandoffUpdate,
    ) -> tuple[CapabilityHandoff, ...]:
        return self.run_store.upsert_capability_handoffs(update.entries)

    def inspect_retention(self) -> RetentionSummary:
        return self.retention_manager.inspect(dry_run=True)

    def cleanup_retention(self) -> RetentionSummary:
        return self.retention_manager.inspect(dry_run=False)

    def get_eval_run(self, eval_run_id: str) -> EvalRunSummary:
        return self.run_store.get_eval_run(eval_run_id)

    def list_eval_runs(self) -> tuple[EvalRunSummary, ...]:
        return self.run_store.list_eval_runs()

    def export_eval_case_from_run(
        self,
        run_id: str,
        *,
        output_dir: Path | None = None,
        case_id: str | None = None,
        name: str | None = None,
        description: str = "",
        tags: tuple[str, ...] = (),
    ) -> EvalCaseExport:
        request = self.get_run_request(run_id)
        result = self.get_run(run_id)
        verification_results = self.get_verification_results(run_id)
        return export_eval_case_record(
            run_id=run_id,
            request=request,
            result=result,
            verification_results=verification_results,
            output_dir=output_dir,
            case_id=case_id,
            name=name,
            description=description,
            tags=tags,
        )

    def list_curated_eval_cases(
        self,
        *,
        corpus_dir: Path | None = None,
        statuses: tuple[EvalCaseStatus, ...] | None = None,
    ):
        resolved_dir = (corpus_dir or default_corpus_dir()).resolve(strict=False)
        return list_eval_cases(corpus_dir=resolved_dir, statuses=statuses)

    def review_eval_case(
        self,
        case_id: str,
        *,
        corpus_dir: Path,
        status: EvalCaseStatus,
        curation_notes: str = "",
    ):
        return review_eval_case(
            corpus_dir=corpus_dir,
            case_id=case_id,
            status=status,
            curation_notes=curation_notes,
        )

    async def run_eval_corpus(
        self,
        *,
        corpus_dir: Path | None = None,
        backend_override: str | None = None,
    ) -> EvalRunSummary:
        resolved_dir = (corpus_dir or default_corpus_dir()).resolve(strict=False)
        cases = load_eval_cases(resolved_dir)
        summary = await self.eval_runner.run_cases(
            cases,
            corpus_name=resolved_dir.name,
            backend_override=backend_override,
        )
        eval_run_id = f"eval_{uuid.uuid4().hex[:12]}"
        persisted = self.artifact_manager.persist_eval_summary(
            eval_run_id=eval_run_id,
            summary=summary,
        )
        return self.run_store.save_eval_run(persisted)

    async def cancel_run(self, run_id: str) -> RunResult:
        return await self.scheduler.cancel(run_id)


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
