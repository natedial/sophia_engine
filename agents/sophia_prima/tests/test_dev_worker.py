from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sophia.config import Settings
from sophia.coding_workers import ClaudeCodeWorker, CodexCodingWorker, create_coding_worker
from sophia_forge_protocol.run_models import ExecutionPolicy, RunRequest


class FakeProcess:
    def __init__(self, *, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


def _build_settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "personality.md").write_text("# Sophia\n\n## Style\nPlain.", encoding="utf-8")
    (config_dir / "soul.md").write_text("Soul", encoding="utf-8")
    return Settings(
        personality_path=config_dir / "personality.md",
        soul_path=config_dir / "soul.md",
        lessons_path=config_dir / "LESSONS.md",
        agent_fs_enforce_read_policy=True,
        agent_fs_enforce_write_policy=True,
        agent_fs_read_allowlist=str(tmp_path),
        agent_fs_write_allowlist=str(tmp_path),
        coding_worker_enabled=enabled,
        coding_worker_workspace_root=tmp_path / "workspace",
        coding_worker_output_dir=tmp_path / ".sophia" / "coding_worker",
    )


async def _fake_process_factory_success(*args, **kwargs):
    output_idx = args.index("-o") + 1
    output_path = Path(args[output_idx])
    payload = {
        "status": "completed",
        "summary": "Implemented the missing scheduler scaffold.",
        "changed_files": ["services/foo/scheduler.py", "docs/runbook.md"],
        "verification": ["uv run pytest services/foo/tests/test_scheduler.py"],
        "follow_ups": [],
        "capabilities_added": [
            {
                "capability_type": "tool",
                "tool_name": "run_nightly_scheduler",
                "service_name": "scrivener",
                "registration_path": "services/sophia_pylon/src/pylon/core.py",
                "description": "Run the nightly scheduler.",
                "when_to_use": "Use when the user asks to trigger the nightly scheduler.",
                "input_schema": {
                    "type": "object",
                    "properties": {"window": {"type": "string"}},
                    "required": ["window"],
                },
                "usage_example": {"window": "1d"},
            }
        ],
    }
    output_path.write_text(json.dumps(payload), encoding="utf-8")
    return FakeProcess()


def test_codex_coding_worker_parses_structured_output(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    codex_bin = tmp_path / "bin" / "codex"
    codex_bin.parent.mkdir(parents=True, exist_ok=True)
    codex_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex_bin.chmod(0o755)
    settings = _build_settings(tmp_path)
    settings = settings.model_copy(update={"codex_command": str(codex_bin)})
    worker = CodexCodingWorker(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
        process_factory=_fake_process_factory_success,
    )

    result = asyncio.run(
        worker.run(
            supervisor_task="Build a scheduler capability for nightly jobs.",
            task_id="dev_task_1",
            timeout_sec=5.0,
        )
    )

    assert result.success is True
    assert result.status == "completed"
    assert "scheduler scaffold" in result.summary.lower()
    assert "services/foo/scheduler.py" in result.changed_files
    assert result.verification == ("uv run pytest services/foo/tests/test_scheduler.py",)
    assert result.capabilities_added[0].tool_name == "run_nightly_scheduler"
    assert result.capabilities_added[0].usage_example == {"window": "1d"}


def test_claude_code_worker_parses_structured_stdout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    claude_bin = tmp_path / "bin" / "claude"
    claude_bin.parent.mkdir(parents=True, exist_ok=True)
    claude_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    claude_bin.chmod(0o755)

    async def _fake_process_factory_success(*args, **kwargs):
        payload = {
            "status": "completed",
            "summary": "Implemented the requested pipeline hook.",
            "changed_files": ["services/foo/pipeline.py"],
            "verification": ["pytest services/foo/tests/test_pipeline.py"],
            "follow_ups": [],
        }
        return FakeProcess(stdout=json.dumps(payload).encode("utf-8"))

    settings = _build_settings(tmp_path).model_copy(
        update={
            "coding_worker_backend": "claude_code",
            "claude_code_command": str(claude_bin),
        }
    )
    worker = ClaudeCodeWorker(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
        process_factory=_fake_process_factory_success,
    )

    result = asyncio.run(
        worker.run(
            supervisor_task="Build the missing ingestion pipeline hook.",
            task_id="coding_task_1",
            timeout_sec=5.0,
        )
    )

    assert result.success is True
    assert result.status == "completed"
    assert result.changed_files == ("services/foo/pipeline.py",)


def test_codex_coding_worker_run_request_uses_execution_policy_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    codex_bin = tmp_path / "bin" / "codex"
    codex_bin.parent.mkdir(parents=True, exist_ok=True)
    codex_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex_bin.chmod(0o755)
    captured: dict[str, object] = {}

    async def _fake_process_factory_capture(*args, **kwargs):
        captured["args"] = args
        output_idx = args.index("-o") + 1
        Path(args[output_idx]).write_text(
            json.dumps(
                {
                    "status": "completed",
                    "summary": "Implemented the request.",
                    "changed_files": [],
                    "verification": [],
                    "follow_ups": [],
                }
            ),
            encoding="utf-8",
        )
        return FakeProcess()

    settings = _build_settings(tmp_path).model_copy(update={"codex_command": str(codex_bin)})
    worker = CodexCodingWorker(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
        process_factory=_fake_process_factory_capture,
    )

    result = asyncio.run(
        worker.run_request(
            RunRequest(
                run_id="forge:codex",
                client_name="sophia_prima",
                task="Implement the request.",
                workspace_root=str(workspace),
                backend="codex",
                timeout_sec=5.0,
                execution_policy=ExecutionPolicy(
                    readable_roots=(str(tmp_path),),
                    writable_roots=(str(tmp_path),),
                    allowed_capabilities=("shell", "write"),
                ),
            )
        )
    )

    assert result.success is True
    assert "-C" in captured["args"]
    assert str(workspace) in captured["args"]


def test_claude_code_worker_run_request_uses_execution_policy_backend_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    claude_bin = tmp_path / "bin" / "claude"
    claude_bin.parent.mkdir(parents=True, exist_ok=True)
    claude_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    claude_bin.chmod(0o755)
    captured: dict[str, object] = {}

    async def _fake_process_factory_capture(*args, **kwargs):
        captured["args"] = args
        payload = {
            "status": "completed",
            "summary": "Implemented the requested pipeline hook.",
            "changed_files": ["services/foo/pipeline.py"],
            "verification": [],
            "follow_ups": [],
        }
        return FakeProcess(stdout=json.dumps(payload).encode("utf-8"))

    settings = _build_settings(tmp_path).model_copy(
        update={
            "coding_worker_backend": "claude_code",
            "claude_code_command": str(claude_bin),
        }
    )
    worker = ClaudeCodeWorker(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
        process_factory=_fake_process_factory_capture,
    )

    result = asyncio.run(
        worker.run_request(
            RunRequest(
                run_id="forge:claude",
                client_name="sophia_prima",
                task="Build the missing ingestion pipeline hook.",
                workspace_root=str(workspace),
                backend="claude_code",
                timeout_sec=5.0,
                execution_policy=ExecutionPolicy(
                    readable_roots=(str(tmp_path),),
                    writable_roots=(str(tmp_path),),
                    allowed_capabilities=("shell", "write"),
                    backend_allowed_tools=("Read", "Edit"),
                ),
            )
        )
    )

    assert result.success is True
    allowed_tools_idx = captured["args"].index("--allowedTools") + 1
    assert captured["args"][allowed_tools_idx] == "Read,Edit"


def test_codex_coding_worker_returns_disabled_when_feature_flag_is_off(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    settings = _build_settings(tmp_path, enabled=False)
    worker = CodexCodingWorker(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
    )

    result = asyncio.run(
        worker.run(
            supervisor_task="Build a data pipeline.",
            task_id="dev_task_disabled",
            timeout_sec=1.0,
        )
    )

    assert result.success is False
    assert result.status == "disabled"
    assert "disabled" in (result.error or "")


def test_coding_worker_factory_selects_backend(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path).model_copy(update={"coding_worker_backend": "claude_code"})
    worker = create_coding_worker(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
    )
    assert isinstance(worker, ClaudeCodeWorker)


def test_settings_accept_legacy_dev_worker_kwargs(tmp_path: Path) -> None:
    settings = Settings(
        personality_path=tmp_path / "personality.md",
        soul_path=tmp_path / "soul.md",
        lessons_path=tmp_path / "LESSONS.md",
        dev_worker_enabled=True,
        dev_worker_workspace_root=tmp_path / "workspace",
        dev_worker_output_dir=tmp_path / ".sophia" / "dev_worker",
        dev_worker_codex_command="/tmp/codex",
    )
    assert settings.coding_worker_enabled is True
    assert settings.coding_worker_workspace_root == tmp_path / "workspace"
    assert settings.codex_command == "/tmp/codex"
