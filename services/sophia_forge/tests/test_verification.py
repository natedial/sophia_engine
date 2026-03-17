from __future__ import annotations

import asyncio
from pathlib import Path

from sophia_forge.config import ForgeSettings
from sophia_forge.core.verification import VerificationRunner, summarize_verification
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge_protocol.verification_models import VerificationPolicy, VerificationStep


def test_verification_runner_executes_explicit_steps(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    runner = VerificationRunner(settings=ForgeSettings(output_dir=tmp_path / "forge_runs"))
    request = RunRequest(
        run_id="forge-verify",
        client_name="sophia_prima",
        task="Implement the missing pipeline hook.",
        workspace_root=str(workspace),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=5.0,
        verification_policy=VerificationPolicy(
            mode="explicit",
            steps=(VerificationStep(name="echo_ok", command="printf ok", required=True),),
        ),
    )
    result = RunResult(
        run_id="forge-verify",
        status="completed",
        summary="Implemented the pipeline hook.",
        changed_files=("services/foo/pipeline.py",),
    )

    outcomes = asyncio.run(runner.run(request, result))

    assert outcomes[0].status == "passed"
    assert summarize_verification(outcomes) == ("passed: printf ok",)


def test_verification_runner_auto_mode_skips_when_no_safe_check(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    runner = VerificationRunner(settings=ForgeSettings(output_dir=tmp_path / "forge_runs"))
    request = RunRequest(
        run_id="forge-auto",
        client_name="sophia_prima",
        task="Implement the missing pipeline hook.",
        workspace_root=str(workspace),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=5.0,
        verification_policy=VerificationPolicy(mode="auto"),
    )
    result = RunResult(
        run_id="forge-auto",
        status="completed",
        summary="Implemented the pipeline hook.",
        changed_files=("services/foo/pipeline.py",),
    )

    outcomes = asyncio.run(runner.run(request, result))

    assert outcomes[0].status == "skipped"
