"""Temporary bridge executor that reuses current Sophia coding workers."""

from __future__ import annotations

from pathlib import Path

from sophia.config import Settings as SophiaSettings
from sophia.coding_workers.factory import create_coding_worker
from sophia.security.filesystem import ReadPolicy, WritePolicy
from sophia_forge.config import ForgeSettings
from sophia_forge.core.scheduler import ForgeExecutor
from sophia_forge_protocol.run_models import RunRequest, RunResult


def build_bridge_executor(*, forge_settings: ForgeSettings) -> ForgeExecutor:
    """Build a temporary executor backed by the current Sophia coding workers."""

    async def _execute(request: RunRequest) -> RunResult:
        run_output_dir = forge_settings.output_dir / _sanitize_run_id(request.run_id or "forge_run")
        sophia_settings = SophiaSettings().model_copy(
            update={
                "coding_worker_enabled": True,
                "coding_worker_backend": request.backend,
                "coding_worker_workspace_root": Path(request.workspace_root),
                "coding_worker_output_dir": run_output_dir,
            }
        )
        readable_roots = tuple(
            Path(path).expanduser().resolve(strict=False)
            for path in (request.execution_policy.readable_roots or request.readable_roots)
        ) or (Path(request.workspace_root).expanduser().resolve(strict=False),)
        writable_roots = tuple(
            Path(path).expanduser().resolve(strict=False)
            for path in (request.execution_policy.writable_roots or request.writable_roots)
        ) or (Path(request.workspace_root).expanduser().resolve(strict=False),)
        if run_output_dir not in writable_roots:
            writable_roots = (*writable_roots, run_output_dir.resolve(strict=False))
        read_policy = ReadPolicy(
            enabled=True,
            allowed_roots=readable_roots,
        )
        write_policy = WritePolicy(
            enabled=True,
            allowed_roots=writable_roots,
        )
        worker = create_coding_worker(
            settings=sophia_settings,
            read_policy=read_policy,
            write_policy=write_policy,
        )
        return await worker.run_request(request)

    return _execute


def _sanitize_run_id(run_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in run_id)
