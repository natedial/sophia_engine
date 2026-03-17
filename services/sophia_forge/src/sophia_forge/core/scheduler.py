"""Background scheduler for forge runs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sophia_forge.core.artifacts import ArtifactManager
from sophia_forge.core.verification import VerificationRunner, summarize_verification
from sophia_forge_protocol.event_models import RunEvent
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge.storage.run_store import ForgeRunStore


ForgeExecutor = Callable[[RunRequest], Awaitable[RunResult]]


class RuntimeScheduler:
    """Runs forge jobs in the background with bounded concurrency."""

    def __init__(
        self,
        *,
        run_store: ForgeRunStore,
        artifact_manager: ArtifactManager,
        verification_runner: VerificationRunner,
        executor: ForgeExecutor | None = None,
        max_concurrent_runs: int = 1,
    ) -> None:
        self.run_store = run_store
        self.artifact_manager = artifact_manager
        self.verification_runner = verification_runner
        self.executor = executor or self._default_executor
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent_runs))
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def enqueue(self, request: RunRequest) -> None:
        run_id = request.run_id or "forge_run"
        self._tasks[run_id] = asyncio.create_task(self._execute(request))

    async def cancel(self, run_id: str) -> RunResult:
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        self.run_store.append_event(
            RunEvent(
                run_id=run_id,
                sequence=len(self.run_store.list_events(run_id)) + 1,
                event_type="run_cancelled",
                timestamp=_utc_now(),
                payload={},
            )
        )
        return self.run_store.cancel_run(run_id)

    async def _execute(self, request: RunRequest) -> None:
        run_id = request.run_id or "forge_run"
        async with self._semaphore:
            self.run_store.mark_running(run_id)
            self.run_store.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=len(self.run_store.list_events(run_id)) + 1,
                    event_type="context_assembled",
                    timestamp=_utc_now(),
                    payload={
                        "workspace_root": request.workspace_root,
                        "readable_roots": list(request.execution_policy.readable_roots),
                        "writable_roots": list(request.execution_policy.writable_roots),
                    },
                )
            )
            self.run_store.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=len(self.run_store.list_events(run_id)) + 1,
                    event_type="run_started",
                    timestamp=_utc_now(),
                    payload={"backend": request.backend},
                )
            )
            self.run_store.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=len(self.run_store.list_events(run_id)) + 1,
                    event_type="backend_started",
                    timestamp=_utc_now(),
                    payload={"backend": request.backend},
                )
            )
            try:
                result = await self.executor(request)
            except asyncio.CancelledError:
                self.run_store.cancel_run(run_id)
                raise
            except Exception as exc:
                result = RunResult(
                    run_id=run_id,
                    status="failed",
                    summary="",
                    error=f"Forge executor failed: {exc}",
                )
            self.run_store.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=len(self.run_store.list_events(run_id)) + 1,
                    event_type="backend_finished",
                    timestamp=_utc_now(),
                    payload={"backend": request.backend, "status": result.status},
                )
            )
            verification_results = await self.verification_runner.run(request, result)
            if verification_results:
                self.run_store.append_event(
                    RunEvent(
                        run_id=run_id,
                        sequence=len(self.run_store.list_events(run_id)) + 1,
                        event_type="verification_started",
                        timestamp=_utc_now(),
                        payload={"count": len(verification_results)},
                    )
                )
                self.run_store.replace_verification_results(run_id, verification_results)
            result = result.model_copy(update={"verification": summarize_verification(verification_results)})
            artifacts = self.artifact_manager.persist_run_artifacts(
                request=request,
                result=result.model_copy(update={"run_id": run_id}),
                verification_results=verification_results,
            )
            self.run_store.replace_artifacts(run_id, artifacts)
            for artifact in artifacts:
                self.run_store.append_event(
                    RunEvent(
                        run_id=run_id,
                        sequence=len(self.run_store.list_events(run_id)) + 1,
                        event_type="artifact_created",
                        timestamp=_utc_now(),
                        payload={
                            "artifact_id": artifact.artifact_id,
                            "artifact_type": artifact.artifact_type,
                        },
                    )
                )
            if verification_results:
                self.run_store.append_event(
                    RunEvent(
                        run_id=run_id,
                        sequence=len(self.run_store.list_events(run_id)) + 1,
                        event_type="verification_finished",
                        timestamp=_utc_now(),
                        payload={"count": len(verification_results)},
                    )
                )
            finalized = result.model_copy(
                update={
                    "run_id": run_id,
                    "artifact_ids": tuple(artifact.artifact_id for artifact in artifacts),
                }
            )
            self.run_store.finish_run(finalized)
            terminal_event = {
                "completed": "run_completed",
                "blocked": "run_blocked",
                "cancelled": "run_cancelled",
            }.get(finalized.status, "run_failed")
            self.run_store.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=len(self.run_store.list_events(run_id)) + 1,
                    event_type=terminal_event,
                    timestamp=_utc_now(),
                    payload={"status": finalized.status},
                )
            )

    @staticmethod
    async def _default_executor(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            status="unavailable",
            summary="",
            error="No forge executor is configured yet",
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
