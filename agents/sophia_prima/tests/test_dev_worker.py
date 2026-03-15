from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sophia.config import Settings
from sophia.dev_worker import CodexDevWorker


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
        dev_worker_enabled=enabled,
        dev_worker_workspace_root=tmp_path / "workspace",
        dev_worker_output_dir=tmp_path / ".sophia" / "dev_worker",
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
    }
    output_path.write_text(json.dumps(payload), encoding="utf-8")
    return FakeProcess()


def test_codex_dev_worker_parses_structured_output(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    codex_bin = tmp_path / "bin" / "codex"
    codex_bin.parent.mkdir(parents=True, exist_ok=True)
    codex_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    codex_bin.chmod(0o755)
    settings = _build_settings(tmp_path)
    settings = settings.model_copy(update={"dev_worker_codex_command": str(codex_bin)})
    worker = CodexDevWorker(
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


def test_codex_dev_worker_returns_disabled_when_feature_flag_is_off(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    settings = _build_settings(tmp_path, enabled=False)
    worker = CodexDevWorker(
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
