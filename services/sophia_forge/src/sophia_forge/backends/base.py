"""Native backend helpers for forge coding execution."""

from __future__ import annotations

import asyncio
import shutil
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Awaitable, Callable

from sophia_forge.config import ForgeSettings
from sophia_forge_protocol.run_models import RunRequest, RunResult, StructuredRunOutput, run_output_schema


ProcessFactory = Callable[..., Awaitable[asyncio.subprocess.Process]]


class BaseForgeBackend(ABC):
    """Base class for forge-managed coding backends."""

    backend_name = "base"

    def __init__(
        self,
        *,
        settings: ForgeSettings,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self.settings = settings
        self.process_factory = process_factory or asyncio.create_subprocess_exec

    @abstractmethod
    async def run(self, request: RunRequest, *, env: Mapping[str, str] | None = None) -> RunResult:
        """Execute one coding run."""

    def _resolve_binary(self, configured_command: str) -> str | None:
        command = configured_command.strip()
        if not command:
            return None
        return shutil.which(command)

    def _prepare_paths(
        self,
        request: RunRequest,
    ) -> tuple[Path, Path, tuple[Path, ...]]:
        workspace_root = Path(request.workspace_root).expanduser().resolve(strict=False)
        writable_roots = tuple(
            Path(path).expanduser().resolve(strict=False)
            for path in (request.execution_policy.writable_roots or request.writable_roots)
        ) or (workspace_root,)
        output_dir = self.settings.output_dir / _sanitize_run_id(request.run_id or "forge_run") / "backend"
        output_dir.mkdir(parents=True, exist_ok=True)
        add_dirs = self._build_add_dirs(workspace_root, writable_roots)
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
            "You are Sophia Forge's delegated coding backend.\n"
            "Inspect the local repository, plan the smallest durable implementation, "
            "and execute it inside the configured coding environment.\n"
            "Constraints:\n"
            "- Work only inside the allowed writable scope.\n"
            "- Prefer minimal, production-appropriate changes over broad refactors.\n"
            "- Do not claim verification steps you did not actually run.\n"
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
    ) -> RunResult:
        trimmed = raw.strip()
        if not trimmed:
            return RunResult(
                success=False,
                status="invalid_output",
                summary="",
                raw_message="",
                error=invalid_json_error,
            )
        try:
            payload = StructuredRunOutput.model_validate_json(trimmed)
        except ValueError:
            return RunResult(
                status="invalid_output",
                summary=trimmed[: self.settings.max_message_chars],
                raw_message=trimmed[: self.settings.max_message_chars],
                error=invalid_json_error,
            )
        except Exception:
            return RunResult(
                status="invalid_output",
                summary=trimmed[: self.settings.max_message_chars],
                raw_message=trimmed[: self.settings.max_message_chars],
                error=invalid_root_error,
            )

        parsed = RunResult.from_structured_output(
            payload,
            raw_message=trimmed[: self.settings.max_message_chars],
            error=None
            if payload.status == "completed"
            else f"{failure_prefix} finished with status={payload.status}",
        )
        return parsed.model_copy(
            update={
                "summary": parsed.summary[: self.settings.max_message_chars],
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


def output_schema() -> dict[str, object]:
    return run_output_schema()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _sanitize_run_id(run_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in run_id)
