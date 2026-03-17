from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from sophia_forge.api.main import create_app
from sophia_forge.config import ForgeSettings
from sophia_forge.core.runtime import ForgeRuntime
from sophia_forge_protocol.run_models import RunRequest, RunResult


async def _fake_executor(request: RunRequest) -> RunResult:
    await asyncio.sleep(0)
    return RunResult(
        run_id=request.run_id,
        status="completed",
        summary="Implemented the requested capability.",
        changed_files=("services/foo/tool.py",),
    )


def test_forge_api_creates_and_completes_run(tmp_path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_fake_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "auto", "steps": []},
                "metadata": {"session_id": "session-1"},
            },
        )
        assert response.status_code == 200
        queued = response.json()
        assert queued["status"] == "queued"
        run_id = queued["run_id"]

        latest = queued
        deadline = time.time() + 1.0
        while time.time() < deadline:
            latest = client.get(f"/v1/runs/{run_id}").json()
            if latest["status"] == "completed":
                break
            time.sleep(0.01)

        assert latest["status"] == "completed"
        assert latest["changed_files"] == ["services/foo/tool.py"]
        assert latest["artifact_ids"]

        events = client.get(f"/v1/runs/{run_id}/events").json()["events"]
        event_types = [event["event_type"] for event in events]
        assert event_types[0] == "run_queued"
        assert "context_assembled" in event_types
        assert "run_started" in event_types
        assert "artifact_created" in event_types
        assert event_types[-1] == "run_completed"

        artifacts = client.get(f"/v1/runs/{run_id}/artifacts").json()["artifacts"]
        artifact_types = {artifact["artifact_type"] for artifact in artifacts}
        assert {"task_spec", "run_result", "changed_files", "summary"} <= artifact_types


def test_forge_api_exposes_structured_verification_results(tmp_path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
            verification_timeout_sec=1.0,
        ),
        executor=_fake_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {
                    "mode": "explicit",
                    "steps": [
                        {
                            "name": "smoke_check",
                            "command": "printf ok",
                            "required": True,
                        }
                    ],
                },
            },
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]

        deadline = time.time() + 1.0
        latest = response.json()
        while time.time() < deadline:
            latest = client.get(f"/v1/runs/{run_id}").json()
            if latest["status"] == "completed":
                break
            time.sleep(0.01)

        assert latest["status"] == "completed"
        verification = client.get(f"/v1/runs/{run_id}/verification").json()["verification_results"]
        assert verification == [
            {
                "name": "smoke_check",
                "status": "passed",
                "command": "printf ok",
                "required": True,
                "details": "ok",
            }
        ]
