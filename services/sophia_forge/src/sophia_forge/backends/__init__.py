"""Backend executors for forge."""

from __future__ import annotations

from typing import Awaitable, Callable

from sophia_forge.backends.claude_code import ClaudeCodeBackend
from sophia_forge.backends.codex import CodexBackend
from sophia_forge.config import ForgeSettings
from sophia_forge_protocol.run_models import RunRequest, RunResult


ForgeExecutor = Callable[[RunRequest], Awaitable[RunResult]]


def build_backend_executor(*, settings: ForgeSettings, process_factory=None) -> ForgeExecutor:
    """Build the native forge backend dispatcher."""

    codex = CodexBackend(settings=settings, process_factory=process_factory)
    claude = ClaudeCodeBackend(settings=settings, process_factory=process_factory)

    async def _execute(request: RunRequest) -> RunResult:
        if request.backend == "codex":
            return await codex.run(request)
        if request.backend == "claude_code":
            return await claude.run(request)
        return RunResult(
            run_id=request.run_id,
            status="failed",
            summary="",
            error=f"Unsupported forge backend: {request.backend}",
        )

    return _execute


__all__ = ["build_backend_executor"]
