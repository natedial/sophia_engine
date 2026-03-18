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


def test_verification_runner_auto_mode_skips_docs_tasks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    runner = VerificationRunner(settings=ForgeSettings(output_dir=tmp_path / "forge_runs"))
    request = RunRequest(
        run_id="forge-docs",
        client_name="sophia_prima",
        task="Update the runbook.",
        workspace_root=str(workspace),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=5.0,
        verification_policy=VerificationPolicy(mode="auto"),
        metadata={"task_type": "docs"},
    )
    result = RunResult(
        run_id="forge-docs",
        status="completed",
        summary="Updated the runbook.",
        changed_files=("docs/runbook.md",),
    )

    outcomes = asyncio.run(runner.run(request, result))

    assert outcomes[0].name == "docs_noop"
    assert outcomes[0].status == "skipped"
    assert outcomes[0].required is False
    assert outcomes[0].details == "Verification recipe skipped for documentation-only task"


def test_verification_runner_auto_mode_finds_service_level_tests(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_file = workspace / "services" / "foo" / "src" / "foo" / "pipeline.py"
    test_file = workspace / "services" / "foo" / "tests" / "test_pipeline.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("def run():\n    return True\n", encoding="utf-8")
    test_file.write_text("def test_run():\n    assert True\n", encoding="utf-8")

    async def _fake_process_factory(command, **kwargs):
        assert command.endswith("services/foo/tests/test_pipeline.py")
        return _CompletedProcess(stdout=b"1 passed\n")

    runner = VerificationRunner(
        settings=ForgeSettings(output_dir=tmp_path / "forge_runs"),
        process_factory=_fake_process_factory,
    )
    request = RunRequest(
        run_id="forge-service-auto",
        client_name="sophia_prima",
        task="Implement the missing pipeline hook.",
        workspace_root=str(workspace),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=5.0,
        verification_policy=VerificationPolicy(mode="auto"),
        metadata={"task_type": "capability"},
    )
    result = RunResult(
        run_id="forge-service-auto",
        status="completed",
        summary="Implemented the pipeline hook.",
        changed_files=("services/foo/src/foo/pipeline.py",),
    )

    outcomes = asyncio.run(runner.run(request, result))

    assert outcomes[0].status == "passed"
    assert outcomes[0].command.endswith("services/foo/tests/test_pipeline.py")


class _CompletedProcess:
    def __init__(self, *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr
