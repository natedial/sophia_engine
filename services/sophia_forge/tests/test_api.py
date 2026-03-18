from __future__ import annotations

import asyncio
import json
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
