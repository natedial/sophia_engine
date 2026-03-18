"""Background scheduler for forge runs."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

from sophia_forge.core.artifacts import ArtifactManager
from sophia_forge.core.environments import EnvironmentManager
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
    ) -> None:
        self.run_store = run_store
        self.artifact_manager = artifact_manager
        self.verification_runner = verification_runner
        self.executor = executor or self._default_executor
        self.workspace_manager = workspace_manager or WorkspaceManager(artifact_manager.settings)
        self.environment_manager = environment_manager or EnvironmentManager(artifact_manager.settings)
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
            prepared_workspace = None
            prepared_environment = None
            effective_request = request
            self.run_store.mark_running(run_id)
            try:
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
                self.run_store.append_event(
                    RunEvent(
                        run_id=run_id,
                        sequence=len(self.run_store.list_events(run_id)) + 1,
                        event_type="context_assembled",
                        timestamp=_utc_now(),
                        payload={
                            "workspace_root": effective_request.workspace_root,
                            "readable_roots": list(effective_request.execution_policy.readable_roots),
                            "writable_roots": list(effective_request.execution_policy.writable_roots),
                            "workspace_strategy": prepared_workspace.strategy,
                            "environment_strategy": prepared_environment.strategy,
                            "injected_secret_env_vars": list(
                                prepared_environment.injected_secret_env_vars
                            ),
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
                result = await _call_executor(
                    self.executor,
                    effective_request,
                    prepared_environment.variables,
                )
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
            try:
                verification_results = await _call_verification_runner(
                    self.verification_runner,
                    effective_request,
                    result,
                    None if prepared_environment is None else prepared_environment.variables,
                )
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
                result = result.model_copy(
                    update={"verification": summarize_verification(verification_results)}
                )
                artifacts = self.artifact_manager.persist_run_artifacts(
                    request=effective_request,
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
            finally:
                final_status = result.status
                if prepared_workspace is not None:
                    self.workspace_manager.cleanup(prepared_workspace, final_status=final_status)
                if prepared_environment is not None:
                    self.environment_manager.cleanup(prepared_environment, final_status=final_status)

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
