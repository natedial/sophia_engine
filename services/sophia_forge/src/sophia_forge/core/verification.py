"""Forge-owned verification runner."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge_protocol.verification_models import VerificationPolicy, VerificationResult, VerificationStep


ProcessFactory = Callable[..., Awaitable[asyncio.subprocess.Process]]


class VerificationRunner:
    """Runs explicit or inferred verification checks after implementation."""

    def __init__(
        self,
        *,
        settings: ForgeSettings,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self.settings = settings
        self.process_factory = process_factory or asyncio.create_subprocess_shell

    async def run(self, request: RunRequest, result: RunResult) -> tuple[VerificationResult, ...]:
        if result.status != "completed":
            return ()
        policy = request.verification_policy
        if policy.mode == "none":
            return ()
        steps = (
            policy.steps
            if policy.mode == "explicit"
            else self._infer_auto_steps(request=request, result=result)
        )
        if not steps:
            return (
                VerificationResult(
                    name="auto_verification",
                    status="skipped",
                    command="",
                    required=False,
                    details="No safe verification command inferred",
                ),
            )
        outcomes: list[VerificationResult] = []
        for step in steps:
            outcomes.append(await self._run_step(request, step))
        return tuple(outcomes)

    async def _run_step(
        self,
        request: RunRequest,
        step: VerificationStep,
    ) -> VerificationResult:
        workspace_root = Path(request.workspace_root).expanduser().resolve(strict=False)
        try:
            process = await self.process_factory(
                step.command,
                cwd=str(workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(0.1, self.settings.verification_timeout_sec),
            )
        except TimeoutError:
            return VerificationResult(
                name=step.name,
                status="failed",
                command=step.command,
                required=step.required,
                details="Verification command timed out",
            )
        except Exception as exc:
            return VerificationResult(
                name=step.name,
                status="failed",
                command=step.command,
                required=step.required,
                details=f"Verification command failed to launch: {exc}",
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        detail = stderr_text or stdout_text or f"exit={process.returncode}"
        if len(detail) > 800:
            detail = detail[:800].rstrip() + "..."
        return VerificationResult(
            name=step.name,
            status="passed" if process.returncode == 0 else "failed",
            command=step.command,
            required=step.required,
            details=detail,
        )

    def _infer_auto_steps(
        self,
        *,
        request: RunRequest,
        result: RunResult,
    ) -> tuple[VerificationStep, ...]:
        workspace_root = Path(request.workspace_root).expanduser().resolve(strict=False)
        pytest_bin = workspace_root / ".venv" / "bin" / "pytest"
        pytest_cmd = str(pytest_bin) if pytest_bin.exists() else "pytest"

        for changed_file in result.changed_files:
            candidate = Path(changed_file)
            if candidate.name.startswith("test_") and candidate.suffix == ".py":
                return (
                    VerificationStep(
                        name="targeted_pytest",
                        command=f"{pytest_cmd} {candidate.as_posix()}",
                        required=False,
                    ),
                )
            if candidate.suffix != ".py":
                continue
            candidates = (
                candidate.parent / "tests" / f"test_{candidate.stem}.py",
                workspace_root / "tests" / f"test_{candidate.stem}.py",
            )
            for test_path in candidates:
                resolved = test_path if test_path.is_absolute() else workspace_root / test_path
                if resolved.exists():
                    relative = os.path.relpath(resolved, workspace_root)
                    return (
                        VerificationStep(
                            name="targeted_pytest",
                            command=f"{pytest_cmd} {relative}",
                            required=False,
                        ),
                    )
        return ()


def summarize_verification(results: tuple[VerificationResult, ...]) -> tuple[str, ...]:
    """Convert structured verification outcomes into compact summary lines."""

    lines: list[str] = []
    for result in results:
        if result.command:
            lines.append(f"{result.status}: {result.command}")
        else:
            lines.append(f"{result.status}: {result.name}")
    return tuple(lines)
