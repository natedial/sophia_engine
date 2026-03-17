"""Client wrapper for coding-runtime requests.

Phase 0 keeps execution inline while standardizing the caller-side contract.
"""

from __future__ import annotations

import json
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx
from sophia.coding_workers.factory import create_coding_worker
from sophia.config import Settings
from sophia.security.filesystem import ReadPolicy, WritePolicy
from sophia_forge_protocol.artifact_models import RunArtifact
from sophia_forge_protocol.event_models import RunEvent
from sophia_forge_protocol.run_models import (
    CapabilityAdoptionReport,
    ExecutionPolicy,
    RunRequest,
    RunResult,
)


class AsyncHttpClient(Protocol):
    async def __aenter__(self) -> "AsyncHttpClient": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...
    async def post(self, url: str, *, json: dict[str, Any]) -> Any: ...
    async def get(self, url: str) -> Any: ...


class ForgeClient:
    """Submit coding work through a runtime-like interface."""

    def __init__(
        self,
        *,
        settings: Settings,
        read_policy: ReadPolicy,
        write_policy: WritePolicy,
        http_client_factory: Callable[[], AsyncHttpClient] | None = None,
    ) -> None:
        self.settings = settings
        self.read_policy = read_policy
        self.write_policy = write_policy
        self._http_client_factory = http_client_factory

    async def run(self, request: RunRequest) -> RunResult:
        mode = self.settings.coding_runtime_mode.strip().lower() or "inline"
        normalized_request = self._normalize_request_policy(request)
        run_id = normalized_request.run_id or "forge_run"
        self._append_event(
            run_id=run_id,
            event_type="run_queued",
            payload={"mode": mode, "backend": normalized_request.backend},
        )
        self._append_event(
            run_id=run_id,
            event_type="context_assembled",
            payload={
                "workspace_root": normalized_request.workspace_root,
                "readable_roots": list(normalized_request.execution_policy.readable_roots),
                "writable_roots": list(normalized_request.execution_policy.writable_roots),
            },
        )
        if mode != "forge_service":
            self._persist_task_spec(normalized_request, mode=mode)
        self._persist_run_request(
            normalized_request,
            mode=mode,
            register_artifact=mode != "forge_service",
        )
        if mode == "inline":
            self._append_event(
                run_id=run_id,
                event_type="run_started",
                payload={"mode": mode, "backend": normalized_request.backend},
            )
            self._append_event(
                run_id=run_id,
                event_type="backend_started",
                payload={"backend": normalized_request.backend},
            )
            worker = create_coding_worker(
                settings=self.settings,
                read_policy=self.read_policy,
                write_policy=self.write_policy,
            )
            result = await worker.run_request(normalized_request)
            self._append_event(
                run_id=run_id,
                event_type="backend_finished",
                payload={
                    "backend": normalized_request.backend,
                    "status": result.status,
                    "success": bool(result.success),
                },
            )
            finalized = self._finalize_run(normalized_request, result=result, mode=mode)
            return finalized
        if mode == "forge_service":
            result = await self._run_via_service(normalized_request)
            return self._finalize_run(normalized_request, result=result, mode=mode)
        result = RunResult(
            run_id=run_id,
            success=False,
            status="failed",
            summary="",
            error=f"Unsupported coding runtime mode: {self.settings.coding_runtime_mode}",
        )
        return self._finalize_run(normalized_request, result=result, mode=mode)

    def _normalize_request_policy(self, request: RunRequest) -> RunRequest:
        policy = request.execution_policy
        if policy.readable_roots and policy.writable_roots and policy.allowed_capabilities:
            return request

        default_tools = tuple(
            item.strip()
            for item in self.settings.claude_code_allowed_tools.split(",")
            if item.strip()
        )
        merged_policy = policy.model_copy(
            update={
                "readable_roots": policy.readable_roots or request.readable_roots,
                "writable_roots": policy.writable_roots or request.writable_roots,
                "allowed_capabilities": policy.allowed_capabilities
                or ("shell", "read", "write", "edit", "grep", "glob", "test"),
                "backend_allowed_tools": policy.backend_allowed_tools or default_tools,
            }
        )
        return request.model_copy(update={"execution_policy": merged_policy})

    async def _run_via_service(self, request: RunRequest) -> RunResult:
        run_id = request.run_id or "forge_run"
        try:
            async with self._make_http_client() as client:
                create_response = await client.post(
                    "/v1/runs",
                    json=request.model_dump(mode="json"),
                )
                create_response.raise_for_status()
                created = RunResult.model_validate(create_response.json())
                service_run_id = created.run_id or run_id
                deadline = asyncio.get_running_loop().time() + max(
                    0.1,
                    self.settings.forge_request_timeout_sec,
                )
                latest = created
                while asyncio.get_running_loop().time() < deadline:
                    status_response = await client.get(f"/v1/runs/{service_run_id}")
                    status_response.raise_for_status()
                    latest = RunResult.model_validate(status_response.json())
                    if latest.status not in {"queued", "running"}:
                        return latest
                    await asyncio.sleep(0.05)
        except httpx.TimeoutException:
            return RunResult(
                run_id=run_id,
                status="timed_out",
                summary="",
                error="Forge service request timed out",
            )
        except httpx.HTTPError as exc:
            return RunResult(
                run_id=run_id,
                status="failed",
                summary="",
                error=f"Forge service request failed: {exc}",
            )
        return RunResult(
            run_id=run_id,
            status="timed_out",
            summary="",
            error="Forge service polling timed out",
        )

    def _make_http_client(self) -> AsyncHttpClient:
        if self._http_client_factory is not None:
            return self._http_client_factory()
        return httpx.AsyncClient(
            base_url=self.settings.forge_base_url.rstrip("/"),
            timeout=self.settings.forge_request_timeout_sec,
        )

    def _persist_run_request(
        self,
        request: RunRequest,
        *,
        mode: str,
        register_artifact: bool = True,
    ) -> Path:
        run_dir = self._ensure_run_dir(request)
        request_path = run_dir / "run_request.json"
        payload = {
            "mode": mode,
            "request": request.model_dump(mode="json"),
        }
        request_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        if register_artifact:
            self._register_artifact(
                run_id=request.run_id or "forge_run",
                artifact_type="run_request",
                path=request_path,
                payload={"mode": mode},
            )
        return request_path

    def _persist_run_result(
        self,
        request: RunRequest,
        *,
        result: RunResult,
        mode: str,
        register_artifact: bool = True,
    ) -> Path:
        run_dir = self._ensure_run_dir(request)
        result_path = run_dir / "run_result.json"
        payload = {
            "mode": mode,
            "run_id": request.run_id or "forge_run",
            "result": result.model_dump(mode="json"),
        }
        result_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        if register_artifact:
            self._register_artifact(
                run_id=request.run_id or "forge_run",
                artifact_type="run_result",
                path=result_path,
                payload={"mode": mode, "status": result.status},
            )
        return result_path

    def persist_capability_adoption(
        self,
        *,
        run_id: str,
        report: CapabilityAdoptionReport,
        mode: str,
    ) -> Path:
        run_dir = self._ensure_run_dir_for_id(run_id)
        report_path = run_dir / "capability_adoption.json"
        payload = {
            "mode": mode,
            "run_id": run_id,
            "report": report.model_dump(mode="json"),
        }
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._register_artifact(
            run_id=run_id,
            artifact_type="capability_adoption",
            path=report_path,
            payload={"mode": mode, "refreshed": report.refreshed},
        )
        return report_path

    def get_run_result(self, run_id: str) -> RunResult:
        run_dir = self._ensure_run_dir_for_id(run_id)
        payload = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
        return RunResult.model_validate(payload["result"])

    def get_run_events(self, run_id: str) -> tuple[RunEvent, ...]:
        run_dir = self._ensure_run_dir_for_id(run_id)
        events_path = run_dir / "events.json"
        if not events_path.exists():
            return ()
        payload = json.loads(events_path.read_text(encoding="utf-8"))
        return tuple(RunEvent.model_validate(item) for item in payload.get("events", []))

    def get_run_artifacts(self, run_id: str) -> tuple[RunArtifact, ...]:
        run_dir = self._ensure_run_dir_for_id(run_id)
        index_path = run_dir / "artifacts.json"
        if not index_path.exists():
            return ()
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        return tuple(RunArtifact.model_validate(item) for item in payload.get("artifacts", []))

    def _finalize_run(self, request: RunRequest, *, result: RunResult, mode: str) -> RunResult:
        run_id = request.run_id or "forge_run"
        artifact_ids = result.artifact_ids
        if mode != "forge_service":
            self._persist_backend_output(request, result=result)
            self._persist_changed_files(request, result=result)
            self._persist_summary(request, result=result)
            self._persist_verification_log(request, result=result)
            artifact_ids = tuple(artifact.artifact_id for artifact in self.get_run_artifacts(run_id))
        finalized = result.model_copy(update={"run_id": run_id, "artifact_ids": artifact_ids})
        self._persist_run_result(
            request,
            result=finalized,
            mode=mode,
            register_artifact=mode != "forge_service",
        )
        terminal_event = {
            "completed": "run_completed",
            "blocked": "run_blocked",
            "cancelled": "run_cancelled",
        }.get(finalized.status, "run_failed")
        self._append_event(
            run_id=run_id,
            event_type=terminal_event,
            payload={
                "status": finalized.status,
                "success": bool(finalized.success),
                "artifact_ids": list(finalized.artifact_ids),
            },
        )
        return finalized

    def _persist_task_spec(self, request: RunRequest, *, mode: str) -> Path:
        run_dir = self._ensure_run_dir(request)
        task_path = run_dir / "task.json"
        payload = {
            "mode": mode,
            "run_id": request.run_id or "forge_run",
            "client_name": request.client_name,
            "task": request.task,
            "backend": request.backend,
            "timeout_sec": request.timeout_sec,
        }
        task_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._register_artifact(
            run_id=request.run_id or "forge_run",
            artifact_type="task_spec",
            path=task_path,
            payload={"mode": mode, "backend": request.backend},
        )
        return task_path

    def _persist_backend_output(self, request: RunRequest, *, result: RunResult) -> Path | None:
        if not result.raw_message:
            return None
        run_dir = self._ensure_run_dir(request)
        path = run_dir / "backend_output.json"
        payload = {
            "run_id": request.run_id or "forge_run",
            "raw_message": result.raw_message,
            "status": result.status,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._register_artifact(
            run_id=request.run_id or "forge_run",
            artifact_type="backend_output",
            path=path,
            payload={"status": result.status},
        )
        return path

    def _persist_changed_files(self, request: RunRequest, *, result: RunResult) -> Path | None:
        if not result.changed_files:
            return None
        run_dir = self._ensure_run_dir(request)
        path = run_dir / "changed_files.json"
        payload = {
            "run_id": request.run_id or "forge_run",
            "changed_files": list(result.changed_files),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._register_artifact(
            run_id=request.run_id or "forge_run",
            artifact_type="changed_files",
            path=path,
            payload={"count": len(result.changed_files)},
        )
        return path

    def _persist_summary(self, request: RunRequest, *, result: RunResult) -> Path | None:
        if not result.summary:
            return None
        run_dir = self._ensure_run_dir(request)
        path = run_dir / "summary.json"
        payload = {
            "run_id": request.run_id or "forge_run",
            "status": result.status,
            "summary": result.summary,
            "error": result.error,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._register_artifact(
            run_id=request.run_id or "forge_run",
            artifact_type="summary",
            path=path,
            payload={"status": result.status},
        )
        return path

    def _persist_verification_log(self, request: RunRequest, *, result: RunResult) -> Path | None:
        if not result.verification:
            return None
        run_id = request.run_id or "forge_run"
        self._append_event(
            run_id=run_id,
            event_type="verification_started",
            payload={"count": len(result.verification)},
        )
        run_dir = self._ensure_run_dir(request)
        verification_dir = run_dir / "verification"
        self.write_policy.ensure_allowed(verification_dir, purpose="forge_verification_dir")
        verification_dir.mkdir(parents=True, exist_ok=True)
        path = verification_dir / "verification.json"
        payload = {
            "run_id": run_id,
            "verification": list(result.verification),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._register_artifact(
            run_id=run_id,
            artifact_type="verification_log",
            path=path,
            payload={"count": len(result.verification)},
        )
        self._append_event(
            run_id=run_id,
            event_type="verification_finished",
            payload={"count": len(result.verification)},
        )
        return path

    def _register_artifact(
        self,
        *,
        run_id: str,
        artifact_type: str,
        path: Path,
        payload: dict[str, object] | None = None,
    ) -> RunArtifact:
        run_dir = self._ensure_run_dir_for_id(run_id)
        index_path = run_dir / "artifacts.json"
        artifacts = list(self.get_run_artifacts(run_id))
        artifact = RunArtifact(
            artifact_id=f"{artifact_type}_{len(artifacts) + 1:03d}",
            run_id=run_id,
            artifact_type=artifact_type,
            content_type="application/json",
            path=str(path),
            payload=payload,
            created_at=_utc_now(),
        )
        artifacts.append(artifact)
        index_payload = {"run_id": run_id, "artifacts": [item.model_dump(mode="json") for item in artifacts]}
        index_path.write_text(json.dumps(index_payload, indent=2, sort_keys=True), encoding="utf-8")
        self._append_event(
            run_id=run_id,
            event_type="artifact_created",
            payload={"artifact_id": artifact.artifact_id, "artifact_type": artifact.artifact_type},
        )
        return artifact

    def _append_event(
        self,
        *,
        run_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
    ) -> RunEvent:
        run_dir = self._ensure_run_dir_for_id(run_id)
        events_path = run_dir / "events.json"
        events = list(self.get_run_events(run_id))
        event = RunEvent(
            run_id=run_id,
            sequence=len(events) + 1,
            event_type=event_type,
            timestamp=_utc_now(),
            payload=payload or {},
        )
        events.append(event)
        events_payload = {"run_id": run_id, "events": [item.model_dump(mode="json") for item in events]}
        events_path.write_text(json.dumps(events_payload, indent=2, sort_keys=True), encoding="utf-8")
        return event

    def _ensure_run_dir(self, request: RunRequest) -> Path:
        return self._ensure_run_dir_for_id(request.run_id or "forge_run")

    def _ensure_run_dir_for_id(self, run_id: str) -> Path:
        output_root = self.settings.coding_worker_output_dir.resolve(strict=False)
        self.write_policy.ensure_allowed(output_root, purpose="coding_worker_output_dir")
        output_root.mkdir(parents=True, exist_ok=True)

        run_dir = output_root / "runs" / _sanitize_run_id(run_id)
        self.write_policy.ensure_allowed(run_dir, purpose="forge_run_dir")
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir


def _sanitize_run_id(run_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in run_id)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
