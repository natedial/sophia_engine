"""Background scheduler for forge runs."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

from sophia_forge.core.artifacts import ArtifactManager
from sophia_forge.core.environments import EnvironmentManager
from sophia_forge.core.outcomes import is_retryable_failure
from sophia_forge.core.promotion import PromotionManager
from sophia_forge.core.verification import VerificationRunner, summarize_verification
from sophia_forge.core.workspaces import WorkspaceManager
from sophia_forge_protocol.event_models import RunEvent
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge.storage.run_store import ForgeRunStore


ForgeExecutor = Callable[[RunRequest, Mapping[str, str] | None], Awaitable[RunResult]]


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
        workspace_manager: WorkspaceManager | None = None,
        environment_manager: EnvironmentManager | None = None,
        promotion_manager: PromotionManager | None = None,
    ) -> None:
        self.run_store = run_store
        self.artifact_manager = artifact_manager
        self.verification_runner = verification_runner
        self.executor = executor or self._default_executor
        self.workspace_manager = workspace_manager or WorkspaceManager(artifact_manager.settings)
        self.environment_manager = environment_manager or EnvironmentManager(artifact_manager.settings)
        self.promotion_manager = promotion_manager or PromotionManager(artifact_manager)
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent_runs))
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def enqueue(self, request: RunRequest) -> None:
        run_id = request.run_id or "forge_run"
        self._tasks[run_id] = asyncio.create_task(self._execute(request))

    async def cancel(self, run_id: str) -> RunResult:
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        self._append_event(run_id, event_type="run_cancelled", payload={})
        result = self.run_store.cancel_run(run_id)
        try:
            request = self.run_store.get_run_request(run_id)
        except KeyError:
            return result
        if request.session_id is not None:
            self.run_store.update_session_from_run(
                session_id=request.session_id,
                run_id=run_id,
                run_status="cancelled",
            )
        return result

    async def _execute(self, request: RunRequest) -> None:
        run_id = request.run_id or "forge_run"
        async with self._semaphore:
            prepared_workspace = None
            prepared_environment = None
            effective_request = request
            finalized_request = request
            self.run_store.mark_running(run_id)
            self.run_store.update_run_metadata(run_id, {"attempt": 1})
            try:
                self._append_event(
                    run_id,
                    event_type="run_progress",
                    payload={"phase": "preparing_context", "message": "Preparing workspace and environment."},
                )
                prepared_workspace = self.workspace_manager.prepare(request)
                prepared_environment = self.environment_manager.prepare(request)
                effective_request = _build_effective_request(
                    request=request,
                    workspace_root=prepared_workspace.workspace_root,
                    readable_roots=prepared_workspace.readable_roots,
                    writable_roots=prepared_workspace.writable_roots,
                    injected_secret_env_vars=prepared_environment.injected_secret_env_vars,
                    environment_strategy=prepared_environment.strategy,
                    environment_root=prepared_environment.env_root,
                )
                self._append_event(
                    run_id,
                    event_type="context_assembled",
                    payload={
                        "workspace_root": effective_request.workspace_root,
                        "readable_roots": list(effective_request.execution_policy.readable_roots),
                        "writable_roots": list(effective_request.execution_policy.writable_roots),
                        "workspace_strategy": prepared_workspace.strategy,
                        "environment_strategy": prepared_environment.strategy,
                        "injected_secret_env_vars": list(prepared_environment.injected_secret_env_vars),
                    },
                )
                self._append_event(
                    run_id,
                    event_type="run_progress",
                    payload={"phase": "context_ready", "message": "Execution context assembled."},
                )
                self._append_event(run_id, event_type="run_started", payload={"backend": request.backend})
                finalized_request, result = await self._execute_with_retry(
                    effective_request,
                    None if prepared_environment is None else prepared_environment.variables,
                )
            except asyncio.CancelledError:
                self.run_store.cancel_run(run_id)
                if request.session_id is not None:
                    self.run_store.update_session_from_run(
                        session_id=request.session_id,
                        run_id=run_id,
                        run_status="cancelled",
                    )
                raise
            except Exception as exc:
                finalized_request = effective_request
                result = RunResult(
                    run_id=run_id,
                    status="failed",
                    summary="",
                    error=f"Forge executor failed: {exc}",
                )
            try:
                self._append_event(
                    run_id,
                    event_type="run_progress",
                    payload={"phase": "verifying", "message": "Running verification and persisting outputs."},
                )
                verification_results = await _call_verification_runner(
                    self.verification_runner,
                    finalized_request,
                    result,
                    None if prepared_environment is None else prepared_environment.variables,
                )
                if verification_results:
                    self._append_event(
                        run_id,
                        event_type="verification_started",
                        payload={"count": len(verification_results)},
                    )
                    self.run_store.replace_verification_results(run_id, verification_results)
                result = result.model_copy(
                    update={"verification": summarize_verification(verification_results)}
                )
                artifacts = list(
                    self.artifact_manager.persist_run_artifacts(
                        request=finalized_request,
                        result=result.model_copy(update={"run_id": run_id}),
                        verification_results=verification_results,
                    )
                )
                checkpoint_record = None
                if finalized_request.session_id is not None:
                    checkpoint_id = f"checkpoint_{run_id}"
                    checkpoint_payload = _build_checkpoint_payload(finalized_request, result)
                    checkpoint_artifact = self.artifact_manager.persist_checkpoint_summary(
                        session_id=finalized_request.session_id,
                        run_id=run_id,
                        checkpoint_id=checkpoint_id,
                        payload=checkpoint_payload,
                    )
                    artifacts.append(checkpoint_artifact)
                    checkpoint_record = self.run_store.create_checkpoint(
                        checkpoint_id=checkpoint_id,
                        session_id=finalized_request.session_id,
                        run_id=run_id,
                        summary_artifact_id=checkpoint_artifact.artifact_id,
                        summary=checkpoint_payload["summary"],
                        metadata={
                            "status": result.status,
                            "changed_files": list(result.changed_files),
                            "verification": list(result.verification),
                        },
                    )
                if checkpoint_record is not None:
                    self._append_event(
                        run_id,
                        event_type="checkpoint_created",
                        payload={
                            "checkpoint_id": checkpoint_record.checkpoint_id,
                            "session_id": checkpoint_record.session_id,
                        },
                    )
                if verification_results:
                    self._append_event(
                        run_id,
                        event_type="verification_finished",
                        payload={"count": len(verification_results)},
                    )
                self._append_event(
                    run_id,
                    event_type="promotion_started",
                    payload={"mode": finalized_request.promotion_policy.mode},
                )
                promotion = self.promotion_manager.promote(
                    request=finalized_request,
                    result=result,
                    verification_results=verification_results,
                )
                artifacts.extend(promotion.artifacts)
                artifacts_tuple = tuple(artifacts)
                self.run_store.replace_artifacts(run_id, artifacts_tuple)
                self.artifact_manager.write_artifact_index(run_id=run_id, artifacts=artifacts_tuple)
                for artifact in artifacts_tuple:
                    self._append_event(
                        run_id,
                        event_type="artifact_created",
                        payload={
                            "artifact_id": artifact.artifact_id,
                            "artifact_type": artifact.artifact_type,
                        },
                    )
                self._append_event(
                    run_id,
                    event_type="promotion_finished",
                    payload={
                        "mode": promotion.mode,
                        "status": promotion.status,
                        "message": promotion.message,
                        "artifact_ids": [artifact.artifact_id for artifact in promotion.artifacts],
                    },
                )
                finalized = result.model_copy(
                    update={
                        "run_id": run_id,
                        "artifact_ids": tuple(artifact.artifact_id for artifact in artifacts_tuple),
                    }
                )
                self.run_store.finish_run(finalized)
                terminal_event = {
                    "completed": "run_completed",
                    "blocked": "run_blocked",
                    "cancelled": "run_cancelled",
                }.get(finalized.status, "run_failed")
                self._append_event(
                    run_id,
                    event_type="run_progress",
                    payload={"phase": "finalizing", "message": "Finalizing run results."},
                )
                self._append_event(
                    run_id,
                    event_type=terminal_event,
                    payload={"status": finalized.status},
                )
                if request.session_id is not None:
                    self.run_store.update_session_from_run(
                        session_id=request.session_id,
                        run_id=run_id,
                        run_status=finalized.status,
                    )
            finally:
                final_status = result.status
                if prepared_workspace is not None:
                    self.workspace_manager.cleanup(prepared_workspace, final_status=final_status)
                if prepared_environment is not None:
                    self.environment_manager.cleanup(prepared_environment, final_status=final_status)

    def _append_event(self, run_id: str, *, event_type: str, payload: dict[str, object]) -> RunEvent:
        return self.run_store.append_event(
            RunEvent(
                run_id=run_id,
                sequence=len(self.run_store.list_events(run_id)) + 1,
                event_type=event_type,
                timestamp=_utc_now(),
                payload=payload,
            )
        )

    async def _execute_with_retry(
        self,
        request: RunRequest,
        env: Mapping[str, str] | None,
    ) -> tuple[RunRequest, RunResult]:
        run_id = request.run_id or "forge_run"
        max_attempts = max(1, request.retry_policy.max_attempts)
        attempt = 1
        final_request = request
        retry_attempted = False

        while True:
            attempt_request = _build_attempt_request(request, attempt=attempt)
            final_request = attempt_request
            self.run_store.update_run_metadata(run_id, {"attempt": attempt})
            self._append_event(
                run_id,
                event_type="backend_started",
                payload={"backend": request.backend, "attempt": attempt},
            )
            self._append_event(
                run_id,
                event_type="run_heartbeat",
                payload={"phase": "backend_running", "backend": request.backend, "attempt": attempt},
            )
            self._append_event(
                run_id,
                event_type="run_progress",
                payload={
                    "phase": "backend_running",
                    "message": f"Backend execution started for attempt {attempt}.",
                    "attempt": attempt,
                },
            )
            try:
                result = await _call_executor(self.executor, attempt_request, env)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                result = RunResult(
                    run_id=run_id,
                    status="failed",
                    summary="",
                    error=f"Forge executor failed: {exc}",
                )

            self._append_event(
                run_id,
                event_type="backend_finished",
                payload={"backend": request.backend, "status": result.status, "attempt": attempt},
            )
            if not _should_retry_request(request=attempt_request, result=result, attempt=attempt):
                if retry_attempted:
                    self._append_event(
                        run_id,
                        event_type="retry_finished",
                        payload={"attempts": attempt, "status": result.status},
                    )
                return final_request, result

            retry_attempted = True
            delay = _retry_delay(
                attempt=attempt,
                initial_backoff_sec=attempt_request.retry_policy.initial_backoff_sec,
                max_backoff_sec=attempt_request.retry_policy.max_backoff_sec,
            )
            self._append_event(
                run_id,
                event_type="retry_scheduled",
                payload={
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "delay_sec": delay,
                    "reason": result.error or result.status,
                },
            )
            self._append_event(
                run_id,
                event_type="run_progress",
                payload={
                    "phase": "retry_wait",
                    "message": f"Scheduling retry attempt {attempt + 1}.",
                    "attempt": attempt + 1,
                    "delay_sec": delay,
                },
            )
            await asyncio.sleep(delay)
            attempt += 1
            self._append_event(
                run_id,
                event_type="retry_started",
                payload={
                    "attempt": attempt,
                    "previous_attempt": attempt - 1,
                    "previous_status": result.status,
                },
            )

    @staticmethod
    async def _default_executor(
        request: RunRequest,
        env: Mapping[str, str] | None = None,
    ) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            status="unavailable",
            summary="",
            error="No forge executor is configured yet",
        )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _build_attempt_request(request: RunRequest, *, attempt: int) -> RunRequest:
    metadata = dict(request.metadata)
    metadata["attempt"] = attempt
    return request.model_copy(update={"metadata": metadata})


def _should_retry_request(*, request: RunRequest, result: RunResult, attempt: int) -> bool:
    if request.retry_policy.mode != "transient_only":
        return False
    if attempt >= max(1, request.retry_policy.max_attempts):
        return False
    return is_retryable_failure(status=result.status, error=result.error)


def _retry_delay(*, attempt: int, initial_backoff_sec: float, max_backoff_sec: float) -> float:
    base = max(0.0, initial_backoff_sec)
    cap = max(base, max_backoff_sec)
    return min(cap, base * (2 ** max(0, attempt - 1)))


def _build_checkpoint_payload(request: RunRequest, result: RunResult) -> dict[str, object]:
    summary = result.summary.strip() or (result.error or result.status)
    return {
        "summary": summary,
        "task": request.task,
        "run_id": request.run_id,
        "session_id": request.session_id,
        "status": result.status,
        "changed_files": list(result.changed_files),
        "verification": list(result.verification),
        "follow_ups": list(result.follow_ups),
    }


def _build_effective_request(
    *,
    request: RunRequest,
    workspace_root,
    readable_roots,
    writable_roots,
    injected_secret_env_vars: tuple[str, ...],
    environment_strategy: str,
    environment_root,
) -> RunRequest:
    execution_policy = request.execution_policy.model_copy(
        update={
            "readable_roots": tuple(str(path) for path in readable_roots),
            "writable_roots": tuple(str(path) for path in writable_roots),
        }
    )
    metadata = dict(request.metadata)
    metadata["effective_workspace_root"] = str(workspace_root)
    metadata["environment_strategy"] = environment_strategy
    metadata["injected_secret_env_vars"] = list(injected_secret_env_vars)
    if environment_root is not None:
        metadata["effective_environment_root"] = str(environment_root)
    return request.model_copy(
        update={
            "workspace_root": str(workspace_root),
            "readable_roots": tuple(str(path) for path in readable_roots),
            "writable_roots": tuple(str(path) for path in writable_roots),
            "execution_policy": execution_policy,
            "metadata": metadata,
        }
    )


async def _call_executor(
    executor: ForgeExecutor,
    request: RunRequest,
    env: Mapping[str, str] | None,
) -> RunResult:
    try:
        signature = inspect.signature(executor)
    except (TypeError, ValueError):
        signature = None

    if signature is not None and len(signature.parameters) <= 1:
        return await executor(request)
    return await executor(request, env)


async def _call_verification_runner(
    verification_runner,
    request: RunRequest,
    result: RunResult,
    env: Mapping[str, str] | None,
):
    try:
        signature = inspect.signature(verification_runner.run)
    except (TypeError, ValueError):
        signature = None

    if signature is not None and len(signature.parameters) <= 2:
        return await verification_runner.run(request, result)
    return await verification_runner.run(request, result, env=env)
