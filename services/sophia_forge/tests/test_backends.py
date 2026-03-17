from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sophia_forge.backends.claude_code import ClaudeCodeBackend
from sophia_forge.backends.codex import CodexBackend
from sophia_forge.config import ForgeSettings
from sophia_forge_protocol.run_models import ExecutionPolicy, RunRequest


class FakeProcess:
    def __init__(self, *, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _build_request(tmp_path: Path, *, backend: str) -> RunRequest:
    return RunRequest(
        run_id=f"forge-{backend}",
        client_name="sophia_prima",
        task="Implement the missing pipeline hook.",
        workspace_root=str(tmp_path / "workspace"),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend=backend,
        timeout_sec=5.0,
        execution_policy=ExecutionPolicy(
            readable_roots=(str(tmp_path),),
            writable_roots=(str(tmp_path),),
        ),
    )


def test_codex_backend_parses_structured_output(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    codex_bin = tmp_path / "bin" / "codex"
    codex_bin.parent.mkdir(parents=True, exist_ok=True)
    codex_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex_bin.chmod(0o755)

    async def _fake_process_factory(*args, **kwargs):
        output_idx = args.index("-o") + 1
        Path(args[output_idx]).write_text(
            json.dumps(
                {
                    "status": "completed",
                    "summary": "Implemented the pipeline hook.",
                    "changed_files": ["services/foo/pipeline.py"],
                    "verification": [],
                    "follow_ups": [],
                }
            ),
            encoding="utf-8",
        )
        return FakeProcess()

    backend = CodexBackend(
        settings=ForgeSettings(
            output_dir=tmp_path / "forge_runs",
            codex_command=str(codex_bin),
        ),
        process_factory=_fake_process_factory,
    )

    result = asyncio.run(backend.run(_build_request(tmp_path, backend="codex")))

    assert result.status == "completed"
    assert result.changed_files == ("services/foo/pipeline.py",)


def test_claude_backend_parses_structured_stdout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    claude_bin = tmp_path / "bin" / "claude"
    claude_bin.parent.mkdir(parents=True, exist_ok=True)
    claude_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    claude_bin.chmod(0o755)

    async def _fake_process_factory(*args, **kwargs):
        return FakeProcess(
            stdout=json.dumps(
                {
                    "status": "completed",
                    "summary": "Implemented the pipeline hook.",
                    "changed_files": ["services/foo/pipeline.py"],
                    "verification": [],
                    "follow_ups": [],
                }
            ).encode("utf-8")
        )

    backend = ClaudeCodeBackend(
        settings=ForgeSettings(
            output_dir=tmp_path / "forge_runs",
            claude_code_command=str(claude_bin),
        ),
        process_factory=_fake_process_factory,
    )

    result = asyncio.run(backend.run(_build_request(tmp_path, backend="claude_code")))

    assert result.status == "completed"
    assert result.changed_files == ("services/foo/pipeline.py",)
