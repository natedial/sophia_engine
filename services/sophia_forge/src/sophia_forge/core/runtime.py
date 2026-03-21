"""Top-level runtime facade for the forge service."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
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
    ControlMessage,
    RunCheckpoint,
    RetentionSummary,
    RunMetricsSummary,
    RunRequest,
    RunResult,
    RunSession,
    RunSessionCreateRequest,
    SessionResumeRequest,
    SessionControlRequest,
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
        session_id = request.session_id
        if session_id is None and request.long_running_mode:
            session_id = f"session_{uuid.uuid4().hex[:12]}"
        if session_id is not None and not self.run_store.session_exists(session_id):
            self.run_store.create_session(
                session_id=session_id,
                client_name=request.client_name,
                task=request.task,
                metadata=request.metadata,
            )
        queued_controls: tuple[ControlMessage, ...] = ()
        effective_task = request.task
        metadata = dict(request.metadata)
        if session_id is not None:
            queued_controls = self.run_store.list_control_messages(session_id, status="queued")
            if queued_controls:
                effective_task = _apply_control_messages(request.task, queued_controls)
                metadata["applied_control_ids"] = [control.control_id for control in queued_controls]
                metadata["applied_control_types"] = [control.control_type for control in queued_controls]
        normalized = request.model_copy(
            update={
                "run_id": run_id,
                "session_id": session_id,
                "task": effective_task,
                "metadata": metadata,
            }
        )
        snapshot = self.run_store.create_run(normalized)
        if session_id is not None:
            self.run_store.bind_run_to_session(session_id=session_id, run_id=run_id)
        self.run_store.append_event(
            RunEvent(
                run_id=run_id,
                sequence=1,
                event_type="run_queued",
                timestamp=_utc_now(),
                payload={"backend": normalized.backend, "client_name": normalized.client_name},
            )
        )
        if session_id is not None:
            self.run_store.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=2,
                    event_type="session_bound",
                    timestamp=_utc_now(),
                    payload={"session_id": session_id},
                )
            )
        if queued_controls:
            applied_controls = self.run_store.mark_control_messages_applied(
                control_ids=tuple(control.control_id for control in queued_controls),
                run_id=run_id,
            )
            next_sequence = len(self.run_store.list_events(run_id)) + 1
            for control in applied_controls:
                self.run_store.append_event(
                    RunEvent(
                        run_id=run_id,
                        sequence=next_sequence,
                        event_type="control_message_applied",
                        timestamp=_utc_now(),
                        payload={
                            "control_id": control.control_id,
                            "control_type": control.control_type,
                            "session_id": control.session_id,
                        },
                    )
                )
                next_sequence += 1
        await self.scheduler.enqueue(normalized)
        return snapshot

    def create_session(self, request: RunSessionCreateRequest) -> RunSession:
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        return self.run_store.create_session(
            session_id=session_id,
            client_name=request.client_name,
            task=request.task,
            metadata=request.metadata,
        )

    def get_session(self, session_id: str) -> RunSession:
        return self.run_store.get_session(session_id)

    def list_session_runs(self, session_id: str) -> tuple[RunResult, ...]:
        return self.run_store.list_session_runs(session_id)

    def queue_session_control(
        self,
        session_id: str,
        request: SessionControlRequest,
    ) -> ControlMessage:
        session = self.run_store.get_session(session_id)
        control = self.run_store.create_control_message(
            control_id=f"control_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            run_id=session.latest_run_id,
            control_type=request.control_type,
            message=request.message,
            metadata=request.metadata,
        )
        if session.latest_run_id is not None:
            self.run_store.append_event(
                RunEvent(
                    run_id=session.latest_run_id,
                    sequence=len(self.run_store.list_events(session.latest_run_id)) + 1,
                    event_type="control_message_queued",
                    timestamp=_utc_now(),
                    payload={
                        "control_id": control.control_id,
                        "control_type": control.control_type,
                        "session_id": session_id,
                    },
                )
            )
        return control

    def list_session_controls(self, session_id: str) -> tuple[ControlMessage, ...]:
        self.run_store.get_session(session_id)
        return self.run_store.list_control_messages(session_id)

    def list_session_checkpoints(self, session_id: str) -> tuple[RunCheckpoint, ...]:
        self.run_store.get_session(session_id)
        return self.run_store.list_checkpoints(session_id)

    async def resume_session(
        self,
        session_id: str,
        request: SessionResumeRequest,
    ) -> RunResult:
        session = self.run_store.get_session(session_id)
        checkpoints = self.run_store.list_checkpoints(session_id)
        if not checkpoints:
            raise KeyError(session_id)
        if request.checkpoint_id is None:
            checkpoint = checkpoints[-1]
        else:
            checkpoint = self.run_store.get_checkpoint(request.checkpoint_id)
            if checkpoint.session_id != session_id:
                raise KeyError(request.checkpoint_id)
        source_request = self.run_store.get_run_request(checkpoint.run_id)
        metadata = dict(source_request.metadata)
        metadata.update(request.metadata)
        metadata["resumed_from_checkpoint_id"] = checkpoint.checkpoint_id
        metadata["resumed_from_run_id"] = checkpoint.run_id
        resumed_request = source_request.model_copy(
            update={
                "run_id": None,
                "session_id": session_id,
                "long_running_mode": True,
                "task": _apply_resume_checkpoint(session.task, checkpoint),
                "metadata": metadata,
            }
        )
        snapshot = await self.submit_run(resumed_request)
        run_id = snapshot.run_id or "forge_run"
        self.run_store.append_event(
            RunEvent(
                run_id=run_id,
                sequence=len(self.run_store.list_events(run_id)) + 1,
                event_type="session_resumed",
                timestamp=_utc_now(),
                payload={
                    "session_id": session_id,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "source_run_id": checkpoint.run_id,
                },
            )
        )
        return snapshot

    def get_run(self, run_id: str) -> RunResult:
        return self.run_store.get_run(run_id)

    def get_run_request(self, run_id: str) -> RunRequest:
        return self.run_store.get_run_request(run_id)

    def get_events(self, run_id: str, *, after_sequence: int | None = None) -> tuple[RunEvent, ...]:
        return self.run_store.list_events(run_id, after_sequence=after_sequence)

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


def _apply_control_messages(task: str, controls: Iterable[ControlMessage]) -> str:
    lines = [task.rstrip(), "", "Session controls:"]
    for control in controls:
        label = "Steer" if control.control_type == "steer" else "Follow-up"
        lines.append(f"- [{label} {control.control_id}] {control.message.strip()}")
    return "\n".join(lines).strip()


def _apply_resume_checkpoint(task: str, checkpoint: RunCheckpoint) -> str:
    return (
        f"{task.rstrip()}\n\n"
        "Resume from checkpoint:\n"
        f"- Checkpoint id: {checkpoint.checkpoint_id}\n"
        f"- Source run id: {checkpoint.run_id}\n"
        f"- Summary: {checkpoint.summary.strip()}"
    ).strip()
