"""Shared contracts and helpers for delegated coding workers."""

from __future__ import annotations

import asyncio
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Awaitable, Callable

from sophia.config import Settings
from sophia.security.filesystem import ReadPolicy, WritePolicy
from sophia_forge_protocol.run_models import (
    ExecutionPolicy,
    RunRequest,
    RunResult as CodingWorkerExecution,
    StructuredRunOutput,
    run_output_schema,
)


ProcessFactory = Callable[..., Awaitable[asyncio.subprocess.Process]]


class BaseCodingWorker(ABC):
    """Base class for bounded coding worker backends."""

    backend_name = "base"

    def __init__(
        self,
        *,
        settings: Settings,
        read_policy: ReadPolicy,
        write_policy: WritePolicy,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self.settings = settings
        self.read_policy = read_policy
        self.write_policy = write_policy
        self.process_factory = process_factory or asyncio.create_subprocess_exec

    async def run(
        self,
        *,
        supervisor_task: str,
        task_id: str,
        timeout_sec: float,
    ) -> CodingWorkerExecution:
        """Compatibility wrapper for existing inline callers."""

        return await self.run_request(
            RunRequest(
                run_id=task_id,
                client_name="sophia_prima_inline",
                task=supervisor_task,
                workspace_root=str(self.settings.coding_worker_workspace_root),
                readable_roots=tuple(
                    str(path.resolve(strict=False)) for path in self.read_policy.allowed_roots
                ),
                writable_roots=tuple(
                    str(path.resolve(strict=False)) for path in self.write_policy.allowed_roots
                ),
                backend=self.backend_name,
                timeout_sec=timeout_sec,
                execution_policy=self._default_execution_policy(),
            )
        )

    @abstractmethod
    async def run_request(self, request: RunRequest) -> CodingWorkerExecution:
        """Run one delegated coding task from a normalized runtime request."""

    def _disabled_execution(self) -> CodingWorkerExecution | None:
        if self.settings.coding_worker_enabled:
            return None
        return CodingWorkerExecution(
            status="disabled",
            summary="",
            error="coding_worker is disabled by configuration",
        )

    def _resolve_binary(self, configured_command: str) -> str | None:
        command = configured_command.strip()
        if not command:
            return None
        return shutil.which(command)

    def _default_execution_policy(self) -> ExecutionPolicy:
        claude_tools = tuple(
            item.strip()
            for item in self.settings.claude_code_allowed_tools.split(",")
            if item.strip()
        )
        return ExecutionPolicy(
            readable_roots=tuple(
                str(path.resolve(strict=False)) for path in self.read_policy.allowed_roots
            ),
            writable_roots=tuple(
                str(path.resolve(strict=False)) for path in self.write_policy.allowed_roots
            ),
            allowed_capabilities=("shell", "read", "write", "edit", "grep", "glob", "test"),
            allowed_command_prefixes=(),
            backend_allowed_tools=claude_tools,
            network_access="inherit",
        )

    def _prepare_workspace(self, request: RunRequest) -> tuple[Path, Path, tuple[Path, ...]]:
        workspace_root = Path(request.workspace_root).resolve(strict=False)
        self.read_policy.ensure_allowed(workspace_root, purpose="coding_worker_workspace_root")
        self.write_policy.ensure_allowed(workspace_root, purpose="coding_worker_workspace_root")

        requested_read_roots = tuple(
            Path(path).resolve(strict=False) for path in request.execution_policy.readable_roots
        )
        for root in requested_read_roots:
            self.read_policy.ensure_allowed(root, purpose="coding_worker_read_scope")

        requested_write_roots = tuple(
            Path(path).resolve(strict=False) for path in request.execution_policy.writable_roots
        )
        if not requested_write_roots:
            requested_write_roots = (workspace_root,)
        for root in requested_write_roots:
            self.write_policy.ensure_allowed(root, purpose="coding_worker_write_scope")

        output_dir = self.settings.coding_worker_output_dir.resolve(strict=False)
        self.write_policy.ensure_allowed(output_dir, purpose="coding_worker_output_dir")
        output_dir.mkdir(parents=True, exist_ok=True)

        add_dirs = self._build_add_dirs(workspace_root, requested_write_roots)
        return workspace_root, output_dir, add_dirs

    def _build_add_dirs(
        self,
        workspace_root: Path,
        writable_roots: tuple[Path, ...],
    ) -> tuple[Path, ...]:
        add_dirs: list[Path] = []
        for root in writable_roots:
            resolved = root.resolve(strict=False)
            if resolved == workspace_root:
                continue
            if _is_within(resolved, workspace_root):
                continue
            add_dirs.append(resolved)
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in add_dirs:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return tuple(deduped)

    def _build_prompt(
        self,
        *,
        request: RunRequest,
        workspace_root: Path,
        add_dirs: tuple[Path, ...],
    ) -> str:
        writable_scope = [str(workspace_root), *[str(path) for path in add_dirs]]
        writable_scope_text = ", ".join(writable_scope) if writable_scope else "(none)"
        capabilities = ", ".join(request.execution_policy.allowed_capabilities) or "(inherit/default)"
        command_prefixes = ", ".join(
            " ".join(prefix) for prefix in request.execution_policy.allowed_command_prefixes
        ) or "(inherit/default)"
        return (
            "You are Sophia's delegated coding worker.\n"
            "Inspect the local repository, plan the smallest durable implementation, "
            "and execute it inside the configured coding environment.\n"
            "Constraints:\n"
            "- Work only inside the allowed writable scope.\n"
            "- Prefer minimal, production-appropriate changes over broad refactors.\n"
            "- Run targeted verification when practical.\n"
            "- If blocked, explain the blocker precisely.\n"
            "- If you add a callable tool, include it in capabilities_added with service_name, "
            "registration_path, description, when_to_use, input_schema, and usage_example.\n"
            "- usage_example must be a JSON object with representative tool arguments, not prose.\n"
            "- input_schema must match the callable tool schema that Sophia Prima will see.\n"
            "- Final output must satisfy the provided JSON schema.\n"
            f"Primary workspace root: {workspace_root}\n"
            f"Writable scope: {writable_scope_text}\n"
            f"Allowed capabilities: {capabilities}\n"
            f"Allowed command prefixes: {command_prefixes}\n"
            f"Network access: {request.execution_policy.network_access}\n"
            "Supervisor task:\n"
            f"{request.task.strip()}"
        )

    def _parse_structured_output(
        self,
        raw: str,
        *,
        invalid_json_error: str,
        invalid_root_error: str,
        failure_prefix: str,
    ) -> CodingWorkerExecution:
        trimmed = raw.strip()
        if not trimmed:
            return CodingWorkerExecution(
                success=False,
                status="invalid_output",
                summary="",
                raw_message="",
                error=invalid_json_error,
            )
        try:
            payload = StructuredRunOutput.model_validate_json(trimmed)
        except ValueError:
            return CodingWorkerExecution(
                status="invalid_output",
                summary=trimmed[: self.settings.coding_worker_max_message_chars],
                raw_message=trimmed[: self.settings.coding_worker_max_message_chars],
                error=invalid_json_error,
            )
        except Exception:
            return CodingWorkerExecution(
                status="invalid_output",
                summary=trimmed[: self.settings.coding_worker_max_message_chars],
                raw_message=trimmed[: self.settings.coding_worker_max_message_chars],
                error=invalid_root_error,
            )

        parsed = CodingWorkerExecution.from_structured_output(
            payload,
            raw_message=trimmed[: self.settings.coding_worker_max_message_chars],
            error=None
            if payload.status == "completed"
            else f"{failure_prefix} finished with status={payload.status}",
        )
        return parsed.model_copy(
            update={
                "summary": parsed.summary[: self.settings.coding_worker_max_message_chars],
            }
        )

    @staticmethod
    def _format_failure(
        *,
        backend_label: str,
        return_code: int,
        stdout_text: str,
        stderr_text: str,
    ) -> str:
        stderr_clean = stderr_text.strip()
        stdout_clean = stdout_text.strip()
        detail = stderr_clean or stdout_clean or "No diagnostic output captured"
        if len(detail) > 800:
            detail = f"{detail[:800].rstrip()}..."
        return f"{backend_label} exec failed with exit code {return_code}: {detail}"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def output_schema() -> dict[str, object]:
    return run_output_schema()
