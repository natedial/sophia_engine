from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from sophia_forge.api.main import create_app
from sophia_forge.config import ForgeSettings
from sophia_forge.core.runtime import ForgeRuntime
from sophia_forge_protocol.run_models import CapabilityHandoff, CapabilityHandoffUpdate, RunRequest, RunResult


async def _fake_executor(request: RunRequest) -> RunResult:
    await asyncio.sleep(0)
    return RunResult(
        run_id=request.run_id,
        status="completed",
        summary="Implemented the requested capability.",
        changed_files=("services/foo/tool.py",),
    )


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "forge-tests@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Forge Tests"],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def _wait_for_terminal_run(client: TestClient, run_id: str, *, timeout_sec: float = 1.0) -> dict:
    latest = client.get(f"/v1/runs/{run_id}").json()
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        latest = client.get(f"/v1/runs/{run_id}").json()
        if latest["status"] not in {"queued", "running"}:
            return latest
        time.sleep(0.01)
    return latest


def _read_sse_events(response, *, stop_event: str) -> list[dict]:
    events: list[dict] = []
    current: dict[str, str] = {}
    for line in response.iter_lines():
        if not line:
            if "data" in current:
                payload = json.loads(current["data"])
                payload["_event"] = current.get("event", "")
                payload["_id"] = current.get("id", "")
                events.append(payload)
                if payload["_event"] == stop_event:
                    break
            current = {}
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        current[field] = value.lstrip()
    return events


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

        latest = _wait_for_terminal_run(client, run_id)

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


def test_forge_api_creates_patch_promotion_artifacts(tmp_path) -> None:
    repo_root = _init_git_repo(tmp_path / "repo")
    target = repo_root / "services" / "foo" / "tool.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "seed tool"],
        check=True,
        capture_output=True,
        text=True,
    )

    async def _patch_executor(request: RunRequest) -> RunResult:
        await asyncio.sleep(0)
        effective_root = Path(request.workspace_root)
        file_path = effective_root / "services" / "foo" / "tool.py"
        file_path.write_text("def run():\n    return False\n", encoding="utf-8")
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Updated the tool implementation.",
            changed_files=("services/foo/tool.py",),
        )

    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_patch_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(repo_root),
                "readable_roots": [str(repo_root)],
                "writable_roots": [str(repo_root)],
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
                "promotion_policy": {"mode": "patch"},
            },
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]

        latest = _wait_for_terminal_run(client, run_id)
        assert latest["status"] == "completed"

        events = client.get(f"/v1/runs/{run_id}/events").json()["events"]
        event_types = [event["event_type"] for event in events]
        assert "promotion_started" in event_types
        assert "promotion_finished" in event_types

        artifacts = client.get(f"/v1/runs/{run_id}/artifacts").json()["artifacts"]
        artifact_types = {artifact["artifact_type"] for artifact in artifacts}
        assert "promotion_status" in artifact_types
        assert "patch" in artifact_types

        patch_artifact = next(artifact for artifact in artifacts if artifact["artifact_type"] == "patch")
        patch_text = Path(patch_artifact["path"]).read_text(encoding="utf-8")
        assert "diff --git a/services/foo/tool.py b/services/foo/tool.py" in patch_text
        assert "-    return True" in patch_text
        assert "+    return False" in patch_text

        status_artifact = next(
            artifact for artifact in artifacts if artifact["artifact_type"] == "promotion_status"
        )
        status_payload = json.loads(Path(status_artifact["path"]).read_text(encoding="utf-8"))
        assert status_payload["mode"] == "patch"
        assert status_payload["status"] == "created"


def test_forge_api_prepares_local_draft_pr_artifacts(tmp_path) -> None:
    repo_root = _init_git_repo(tmp_path / "repo")
    target = repo_root / "services" / "foo" / "tool.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "seed tool"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "-C", str(repo_root), "branch", "-M", "main"], check=True, capture_output=True, text=True)

    async def _draft_pr_executor(request: RunRequest) -> RunResult:
        await asyncio.sleep(0)
        effective_root = Path(request.workspace_root)
        file_path = effective_root / "services" / "foo" / "tool.py"
        file_path.write_text("def run():\n    return False\n", encoding="utf-8")
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Updated the tool implementation.",
            changed_files=("services/foo/tool.py",),
        )

    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_draft_pr_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(repo_root),
                "readable_roots": [str(repo_root)],
                "writable_roots": [str(repo_root)],
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
                "promotion_policy": {"mode": "draft_pr", "base_branch": "main"},
            },
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]

        latest = _wait_for_terminal_run(client, run_id)
        assert latest["status"] == "completed"

        artifacts = client.get(f"/v1/runs/{run_id}/artifacts").json()["artifacts"]
        artifact_types = {artifact["artifact_type"] for artifact in artifacts}
        assert "promotion_status" in artifact_types
        assert "pr_request" in artifact_types

        pr_request = next(artifact for artifact in artifacts if artifact["artifact_type"] == "pr_request")
        pr_payload = json.loads(Path(pr_request["path"]).read_text(encoding="utf-8"))
        assert pr_payload["mode"] == "draft_pr"
        assert pr_payload["base_branch"] == "main"
        assert pr_payload["branch_name"].startswith("forge/")
        assert pr_payload["publish_status"] == "not_configured"

        status_artifact = next(
            artifact for artifact in artifacts if artifact["artifact_type"] == "promotion_status"
        )
        status_payload = json.loads(Path(status_artifact["path"]).read_text(encoding="utf-8"))
        assert status_payload["mode"] == "draft_pr"
        assert status_payload["status"] == "prepared"

        branch_name = pr_payload["branch_name"]
        current_branch = subprocess.run(
            ["git", "-C", str(repo_root), "branch", "--show-current"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert current_branch == branch_name
        head_message = subprocess.run(
            ["git", "-C", str(repo_root), "log", "-1", "--pretty=%s"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert head_message == "Updated the tool implementation."


def test_forge_api_creates_session_and_links_runs(tmp_path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_fake_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        session_response = client.post(
            "/v1/sessions",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool over multiple runs.",
                "metadata": {"source": "test"},
            },
        )
        assert session_response.status_code == 200
        session = session_response.json()
        session_id = session["session_id"]
        assert session["status"] == "active"
        assert session["run_ids"] == []

        run_response = client.post(
            "/v1/runs",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "session_id": session_id,
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
            },
        )
        assert run_response.status_code == 200
        run_id = run_response.json()["run_id"]

        latest = _wait_for_terminal_run(client, run_id)
        assert latest["status"] == "completed"

        fetched_session = client.get(f"/v1/sessions/{session_id}")
        assert fetched_session.status_code == 200
        payload = fetched_session.json()
        assert payload["latest_run_id"] == run_id
        assert payload["run_ids"] == [run_id]
        assert payload["status"] == "completed"

        listed_runs = client.get(f"/v1/sessions/{session_id}/runs")
        assert listed_runs.status_code == 200
        assert listed_runs.json()["runs"][0]["run_id"] == run_id

        events = client.get(f"/v1/runs/{run_id}/events").json()["events"]
        assert any(event["event_type"] == "session_bound" for event in events)


def test_forge_api_auto_creates_session_for_long_running_mode(tmp_path) -> None:
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
                "long_running_mode": True,
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
            },
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]
        _wait_for_terminal_run(client, run_id)

        request_payload = client.get(f"/v1/runs/{run_id}/request").json()
        assert request_payload["session_id"]
        session_id = request_payload["session_id"]
        session = client.get(f"/v1/sessions/{session_id}").json()
        assert session["run_ids"] == [run_id]


def test_forge_api_persists_and_applies_session_controls(tmp_path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_fake_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        session_response = client.post(
            "/v1/sessions",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool over multiple runs.",
            },
        )
        assert session_response.status_code == 200
        session_id = session_response.json()["session_id"]

        control_response = client.post(
            f"/v1/sessions/{session_id}/control",
            json={
                "control_type": "steer",
                "message": "Prioritize the failing tests before broader cleanup.",
            },
        )
        assert control_response.status_code == 200
        control = control_response.json()
        assert control["status"] == "queued"

        controls_payload = client.get(f"/v1/sessions/{session_id}/controls")
        assert controls_payload.status_code == 200
        assert controls_payload.json()["controls"][0]["control_id"] == control["control_id"]

        run_response = client.post(
            "/v1/runs",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "session_id": session_id,
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
            },
        )
        assert run_response.status_code == 200
        run_id = run_response.json()["run_id"]
        _wait_for_terminal_run(client, run_id)

        updated_controls = client.get(f"/v1/sessions/{session_id}/controls").json()["controls"]
        assert updated_controls[0]["status"] == "applied"
        assert updated_controls[0]["run_id"] == run_id

        stored_request = client.get(f"/v1/runs/{run_id}/request").json()
        assert "Session controls:" in stored_request["task"]
        assert control["control_id"] in stored_request["task"]
        assert stored_request["metadata"]["applied_control_ids"] == [control["control_id"]]

        events = client.get(f"/v1/runs/{run_id}/events").json()["events"]
        event_types = [event["event_type"] for event in events]
        assert "control_message_applied" in event_types


def test_forge_api_queues_control_event_against_latest_session_run(tmp_path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_fake_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        session_id = client.post(
            "/v1/sessions",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool over multiple runs.",
            },
        ).json()["session_id"]

        run_id = client.post(
            "/v1/runs",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "session_id": session_id,
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
            },
        ).json()["run_id"]
        _wait_for_terminal_run(client, run_id)

        response = client.post(
            f"/v1/sessions/{session_id}/control",
            json={
                "control_type": "follow_up",
                "message": "Add documentation after the implementation.",
            },
        )
        assert response.status_code == 200

        events = client.get(f"/v1/runs/{run_id}/events").json()["events"]
        assert any(event["event_type"] == "control_message_queued" for event in events)


def test_forge_api_creates_checkpoints_for_session_runs_and_can_resume(tmp_path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_fake_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        session_id = client.post(
            "/v1/sessions",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool over multiple runs.",
            },
        ).json()["session_id"]

        first_run_id = client.post(
            "/v1/runs",
            json={
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "session_id": session_id,
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
            },
        ).json()["run_id"]
        _wait_for_terminal_run(client, first_run_id)

        checkpoints_response = client.get(f"/v1/sessions/{session_id}/checkpoints")
        assert checkpoints_response.status_code == 200
        checkpoints = checkpoints_response.json()["checkpoints"]
        assert len(checkpoints) == 1
        checkpoint = checkpoints[0]
        assert checkpoint["run_id"] == first_run_id

        first_run_artifacts = client.get(f"/v1/runs/{first_run_id}/artifacts").json()["artifacts"]
        assert any(artifact["artifact_type"] == "checkpoint_summary" for artifact in first_run_artifacts)

        resume_response = client.post(
            f"/v1/sessions/{session_id}/resume",
            json={"checkpoint_id": checkpoint["checkpoint_id"]},
        )
        assert resume_response.status_code == 200
        resumed_run_id = resume_response.json()["run_id"]
        assert resumed_run_id != first_run_id
        _wait_for_terminal_run(client, resumed_run_id)

        resumed_request = client.get(f"/v1/runs/{resumed_run_id}/request").json()
        assert "Resume from checkpoint:" in resumed_request["task"]
        assert checkpoint["checkpoint_id"] in resumed_request["task"]
        assert resumed_request["metadata"]["resumed_from_checkpoint_id"] == checkpoint["checkpoint_id"]
        assert resumed_request["metadata"]["resumed_from_run_id"] == first_run_id

        resumed_events = client.get(f"/v1/runs/{resumed_run_id}/events").json()["events"]
        assert any(event["event_type"] == "session_resumed" for event in resumed_events)

        updated_session = client.get(f"/v1/sessions/{session_id}").json()
        assert updated_session["latest_run_id"] == resumed_run_id
        assert updated_session["latest_checkpoint_id"]
        assert updated_session["run_ids"] == [first_run_id, resumed_run_id]


def test_forge_api_filters_events_after_sequence_and_streams_sse(tmp_path) -> None:
    async def _streaming_executor(request: RunRequest) -> RunResult:
        await asyncio.sleep(0.05)
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Implemented the requested capability.",
            changed_files=("services/foo/tool.py",),
        )

    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_streaming_executor,
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
                "verification_policy": {"mode": "none", "steps": []},
            },
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]

        with client.stream("GET", f"/v1/runs/{run_id}/events/stream?after_sequence=1") as stream:
            assert stream.status_code == 200
            streamed_events = _read_sse_events(stream, stop_event="run_completed")

        event_types = [event["_event"] for event in streamed_events]
        assert "run_progress" in event_types
        assert "run_heartbeat" in event_types
        assert event_types[-1] == "run_completed"
        assert all(int(event["_id"]) > 1 for event in streamed_events)

        latest = _wait_for_terminal_run(client, run_id)
        assert latest["status"] == "completed"

        all_events = client.get(f"/v1/runs/{run_id}/events").json()["events"]
        filtered_events = client.get(f"/v1/runs/{run_id}/events?after_sequence=1").json()["events"]
        assert len(filtered_events) < len(all_events)
        assert filtered_events[0]["sequence"] > 1
        assert filtered_events[-1]["event_type"] == "run_completed"


def test_forge_api_retries_transient_failures_when_enabled(tmp_path) -> None:
    attempts = 0

    async def _retrying_executor(request: RunRequest) -> RunResult:
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0)
        if attempts == 1:
            return RunResult(
                run_id=request.run_id,
                status="timed_out",
                summary="",
                error="provider timed out",
            )
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Implemented after retry.",
            changed_files=("services/foo/tool.py",),
        )

    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
            verification_timeout_sec=1.0,
        ),
        executor=_retrying_executor,
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
                "retry_policy": {
                    "mode": "transient_only",
                    "max_attempts": 2,
                    "initial_backoff_sec": 0.01,
                    "max_backoff_sec": 0.01,
                },
                "verification_policy": {"mode": "none", "steps": []},
            },
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]

        latest = _wait_for_terminal_run(client, run_id)
        assert latest["status"] == "completed"
        assert attempts == 2

        events = client.get(f"/v1/runs/{run_id}/events").json()["events"]
        event_types = [event["event_type"] for event in events]
        assert "retry_scheduled" in event_types
        assert "retry_started" in event_types
        assert "retry_finished" in event_types
        assert event_types[-1] == "run_completed"

        retry_scheduled = next(event for event in events if event["event_type"] == "retry_scheduled")
        assert retry_scheduled["payload"]["attempt"] == 1
        assert retry_scheduled["payload"]["next_attempt"] == 2

        summary = client.get("/v1/metrics/summary").json()
        assert summary["retry_rate"] == 1.0


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

        latest = _wait_for_terminal_run(client, run_id)

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


def test_forge_api_exposes_metrics_summary(tmp_path) -> None:
    async def _metrics_executor(request: RunRequest) -> RunResult:
        await asyncio.sleep(0)
        if request.metadata.get("outcome") == "fail":
            return RunResult(
                run_id=request.run_id,
                status="failed",
                summary="",
                error="backend launch failed: missing binary",
            )
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Implemented the requested capability.",
            changed_files=("services/foo/tool.py",),
        )

    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
            verification_timeout_sec=1.0,
        ),
        executor=_metrics_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        payloads = [
            {
                "client_name": "sophia_prima",
                "task": "Implement a missing tool.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {
                    "mode": "explicit",
                    "steps": [{"name": "smoke_check", "command": "printf ok", "required": True}],
                },
                "metadata": {"task_type": "capability"},
            },
            {
                "client_name": "sophia_prima",
                "task": "Retry a missing tool.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
                "metadata": {"task_type": "capability", "retry_of_run_id": "forge-prev", "attempt": 2},
            },
            {
                "client_name": "sophia_prima",
                "task": "Broken run.",
                "workspace_root": str(tmp_path),
                "readable_roots": [str(tmp_path)],
                "writable_roots": [str(tmp_path)],
                "backend": "codex",
                "timeout_sec": 30.0,
                "verification_policy": {"mode": "none", "steps": []},
                "metadata": {"task_type": "capability", "outcome": "fail"},
            },
        ]
        run_ids: list[str] = []
        for payload in payloads:
            response = client.post("/v1/runs", json=payload)
            assert response.status_code == 200
            run_ids.append(response.json()["run_id"])

        deadline = time.time() + 1.0
        while time.time() < deadline:
            statuses = [client.get(f"/v1/runs/{run_id}").json()["status"] for run_id in run_ids]
            if all(status not in {"queued", "running"} for status in statuses):
                break
            time.sleep(0.01)

        summary = client.get("/v1/metrics/summary").json()
        assert summary["total_runs"] == 3
        assert summary["completed_runs"] == 2
        assert summary["failed_runs"] == 1
        assert summary["retry_rate"] == (1 / 3)
        assert summary["runs_with_verification"] == 1
        assert summary["verification_pass_rate"] == 1.0
        assert summary["common_failure_classes"] == [
            {"failure_class": "backend_launch_failed", "count": 1}
        ]
        assert summary["task_types"] == [
            {"task_type": "capability", "total_runs": 3, "completed_runs": 2}
        ]


def test_forge_api_exposes_retention_summary(tmp_path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_fake_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        summary = client.get("/v1/retention/summary")
        assert summary.status_code == 200
        payload = summary.json()
        assert payload["dry_run"] is True
        assert payload["workspaces"]["category"] == "workspaces"

        cleaned = client.post("/v1/retention/cleanup")
        assert cleaned.status_code == 200
        assert cleaned.json()["dry_run"] is False


def test_forge_api_persists_capability_handoffs(tmp_path) -> None:
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
            "/v1/capabilities",
            json=CapabilityHandoffUpdate(
                entries=(
                    CapabilityHandoff(
                        tool_name="get_market_ohlcv",
                        service_name="scrivener",
                        registration_path="services/sophia_pylon/src/pylon/core.py",
                        usage_example={"symbol": "ZN"},
                    ),
                )
            ).model_dump(mode="json"),
        )
        assert response.status_code == 200
        assert response.json()["entries"][0]["tool_name"] == "get_market_ohlcv"

        listed = client.get("/v1/capabilities")
        assert listed.status_code == 200
        assert listed.json()["entries"][0]["tool_name"] == "get_market_ohlcv"


def test_forge_api_replays_and_lists_eval_runs(tmp_path) -> None:
    runtime_request = RunRequest(
        run_id="eval-api-success",
        client_name="sophia_prima",
        task="Implement a tool.",
        workspace_root=str(tmp_path),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        verification_policy={"mode": "none", "steps": ()},
        metadata={"task_type": "capability"},
    )
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    (corpus_dir / "case.json").write_text(
        json.dumps(
            {
                "case_id": "api-success",
                "name": "API replay works",
                "request": runtime_request.model_dump(mode="json"),
                "expectation": {
                    "status": "completed",
                    "changed_files_subset": ["services/foo/tool.py"],
                },
            }
        ),
        encoding="utf-8",
    )

    async def _eval_executor(request: RunRequest) -> RunResult:
        await asyncio.sleep(0)
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Implemented the requested capability.",
            changed_files=("services/foo/tool.py",),
        )

    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        ),
        executor=_eval_executor,
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.post(
            "/v1/evals/replay",
            json={"corpus_dir": str(corpus_dir), "backend_override": "codex"},
        )
        assert response.status_code == 200
        summary = response.json()
        assert summary["passed_cases"] == 1
        assert summary["eval_run_id"]
        assert summary["artifact_id"]
        assert summary["summary_path"]

        listed = client.get("/v1/evals").json()["eval_runs"]
        assert listed[0]["eval_run_id"] == summary["eval_run_id"]

        fetched = client.get(f"/v1/evals/{summary['eval_run_id']}").json()
        assert fetched["eval_run_id"] == summary["eval_run_id"]
        assert fetched["results"][0]["case_id"] == "api-success"


def test_forge_api_exports_completed_run_to_candidate_eval_case(tmp_path) -> None:
    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "runs",
        )
    )
    request = RunRequest(
        run_id="forge-export-api",
        client_name="sophia_prima",
        task="Implement a scheduler hook.",
        workspace_root=str(tmp_path),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=30.0,
        verification_policy={"mode": "none", "steps": ()},
        metadata={"task_type": "capability"},
    )
    runtime.run_store.create_run(request)
    runtime.run_store.finish_run(
        RunResult(
            run_id="forge-export-api",
            status="completed",
            summary="Implemented the scheduler hook.",
            changed_files=("services/foo/scheduler.py",),
        )
    )
    app = create_app(runtime=runtime)

    with TestClient(app) as client:
        request_payload = client.get("/v1/runs/forge-export-api/request").json()
        assert request_payload["run_id"] == "forge-export-api"
        assert request_payload["task"] == "Implement a scheduler hook."

        export_dir = tmp_path / "exported_corpus"
        response = client.post(
            "/v1/evals/export/forge-export-api",
            json={
                "output_dir": str(export_dir),
                "tags": ["scheduler"],
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["run_id"] == "forge-export-api"
        assert payload["case"]["expectation"]["status"] == "completed"
        assert payload["case"]["status"] == "candidate"
        assert "scheduler" in payload["case"]["tags"]
        assert Path(payload["output_path"]).exists()

        listed_candidates = client.get(
            "/v1/evals/cases",
            params={"corpus_dir": str(export_dir), "status": "candidate"},
        ).json()["cases"]
        assert listed_candidates[0]["case_id"] == payload["case"]["case_id"]

        reviewed = client.post(
            f"/v1/evals/cases/{payload['case']['case_id']}/review",
            json={
                "corpus_dir": str(export_dir),
                "status": "approved",
                "curation_notes": "Approved for the default benchmark.",
            },
        ).json()
        assert reviewed["status"] == "approved"
        assert reviewed["curation_notes"] == "Approved for the default benchmark."

        approved = client.get(
            "/v1/evals/cases",
            params={"corpus_dir": str(export_dir), "status": "approved"},
        ).json()["cases"]
        assert approved[0]["case_id"] == payload["case"]["case_id"]
