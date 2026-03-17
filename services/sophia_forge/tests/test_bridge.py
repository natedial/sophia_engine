from __future__ import annotations

import asyncio
from pathlib import Path

from sophia_forge.backends.bridge import build_bridge_executor
from sophia_forge.config import ForgeSettings
from sophia_forge_protocol.run_models import ExecutionPolicy, RunRequest, RunResult


def test_bridge_executor_uses_current_coding_worker(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeWorker:
        async def run_request(self, request: RunRequest) -> RunResult:
            captured["request"] = request
            return RunResult(
                run_id=request.run_id,
                status="completed",
                summary="Executed via bridge.",
            )

    monkeypatch.setattr(
        "sophia_forge.backends.bridge.create_coding_worker",
        lambda **kwargs: FakeWorker(),
    )

    executor = build_bridge_executor(
        forge_settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "forge_runs",
        )
    )

    result = asyncio.run(
        executor(
            RunRequest(
                run_id="forge-run-1",
                client_name="sophia_prima",
                task="Implement a missing tool.",
                workspace_root=str(tmp_path),
                readable_roots=(str(tmp_path),),
                writable_roots=(str(tmp_path),),
                backend="codex",
                timeout_sec=30.0,
                execution_policy=ExecutionPolicy(
                    readable_roots=(str(tmp_path),),
                    writable_roots=(str(tmp_path),),
                ),
            )
        )
    )

    assert result.status == "completed"
    assert captured["request"].run_id == "forge-run-1"
