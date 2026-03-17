from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from sophia.config import Settings
from sophia.forge_client import ForgeClient
from sophia_forge.api.main import create_app
from sophia_forge.config import ForgeSettings
from sophia_forge.core.runtime import ForgeRuntime
from sophia_forge_protocol.run_models import (
    CapabilityAdded,
    CapabilityAdoption,
    CapabilityAdoptionReport,
    ExecutionPolicy,
    RunRequest,
    RunResult,
)


def _build_settings(tmp_path: Path, *, runtime_mode: str = "inline") -> Settings:
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
        coding_worker_enabled=True,
        coding_worker_workspace_root=tmp_path / "workspace",
        coding_worker_output_dir=tmp_path / ".sophia" / "coding_worker",
        coding_runtime_mode=runtime_mode,
    )


def _build_request(tmp_path: Path) -> RunRequest:
    return RunRequest(
        run_id="parent:coding",
        client_name="sophia_prima",
        task="Implement the missing pipeline hook.",
        workspace_root=str(tmp_path / "workspace"),
        readable_roots=(str(tmp_path),),
        writable_roots=(str(tmp_path),),
        backend="codex",
        timeout_sec=5.0,
    )


def test_forge_client_inline_mode_uses_coding_worker(monkeypatch, tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    client = ForgeClient(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
    )
    captured: dict[str, object] = {}

    class FakeWorker:
        async def run_request(self, request: RunRequest) -> RunResult:
            captured["request"] = request
            return RunResult(
                status="completed",
                summary="Implemented the pipeline hook.",
                changed_files=("services/foo/pipeline.py",),
                capabilities_added=(
                    CapabilityAdded(
                        tool_name="get_market_ohlcv",
                        service_name="scrivener",
                        registration_path="services/sophia_pylon/src/pylon/core.py",
                        description="Get OHLCV market data.",
                        when_to_use="Use when the user asks for OHLCV market data.",
                        input_schema={
                            "type": "object",
                            "properties": {"symbol": {"type": "string"}},
                            "required": ["symbol"],
                        },
                        usage_example={"symbol": "ZN"},
                    ),
                ),
            )

    monkeypatch.setattr("sophia.forge_client.create_coding_worker", lambda **kwargs: FakeWorker())

    result = asyncio.run(client.run(_build_request(tmp_path)))

    assert result.success is True
    request = captured["request"]
    assert isinstance(request, RunRequest)
    assert request.task == "Implement the missing pipeline hook."
    assert request.run_id == "parent:coding"
    assert request.execution_policy.allowed_capabilities == (
        "shell",
        "read",
        "write",
        "edit",
        "grep",
        "glob",
        "test",
    )
    request_path = tmp_path / ".sophia" / "coding_worker" / "runs" / "parent_coding" / "run_request.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "inline"
    assert payload["request"]["run_id"] == "parent:coding"
    assert payload["request"]["execution_policy"]["allowed_capabilities"] == [
        "shell",
        "read",
        "write",
        "edit",
        "grep",
        "glob",
        "test",
    ]
    result_path = tmp_path / ".sophia" / "coding_worker" / "runs" / "parent_coding" / "run_result.json"
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert result_payload["mode"] == "inline"
    assert result_payload["run_id"] == "parent:coding"
    assert result_payload["result"]["status"] == "completed"
    assert result_payload["result"]["success"] is True
    assert result_payload["result"]["capabilities_added"][0]["tool_name"] == "get_market_ohlcv"
    assert result_payload["result"]["capabilities_added"][0]["usage_example"] == {"symbol": "ZN"}
    assert result_payload["result"]["artifact_ids"]
    events = client.get_run_events("parent:coding")
    assert events[0].event_type == "run_queued"
    assert any(event.event_type == "backend_started" for event in events)
    assert events[-1].event_type == "run_completed"
    artifacts = client.get_run_artifacts("parent:coding")
    artifact_types = {artifact.artifact_type for artifact in artifacts}
    assert {"task_spec", "run_request", "changed_files", "summary", "run_result"} <= artifact_types
    persisted = client.get_run_result("parent:coding")
    assert persisted.status == "completed"


def test_forge_client_reports_service_request_failures(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path, runtime_mode="forge_service")
    client = ForgeClient(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
    )

    result = asyncio.run(client.run(_build_request(tmp_path)))

    assert result.success is False
    assert result.status == "failed"


def test_forge_client_service_mode_polls_forge_api(tmp_path: Path) -> None:
    async def _fake_executor(request: RunRequest) -> RunResult:
        await asyncio.sleep(0)
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Implemented through forge service.",
            changed_files=("services/foo/pipeline.py",),
        )

    runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "forge_runs",
        ),
        executor=_fake_executor,
    )
    app = create_app(runtime=runtime)
    transport = httpx.ASGITransport(app=app)

    def _http_client_factory():
        return httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0)

    settings = _build_settings(tmp_path, runtime_mode="forge_service").model_copy(
        update={"forge_base_url": "http://testserver", "forge_request_timeout_sec": 1.0}
    )
    client = ForgeClient(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
        http_client_factory=_http_client_factory,
    )

    result = asyncio.run(client.run(_build_request(tmp_path)))

    assert result.success is True
    assert result.status == "completed"
    assert result.summary == "Implemented through forge service."
    assert result.changed_files == ("services/foo/pipeline.py",)
    run_dir = tmp_path / ".sophia" / "coding_worker" / "runs" / "parent_coding"
    assert (run_dir / "run_request.json").exists()
    assert (run_dir / "run_result.json").exists()
    assert not (run_dir / "artifacts.json").exists()


def test_forge_client_preserves_explicit_execution_policy(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    client = ForgeClient(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
    )
    request = _build_request(tmp_path).model_copy(
        update={
            "execution_policy": ExecutionPolicy(
                readable_roots=(str(tmp_path / "read"),),
                writable_roots=(str(tmp_path / "write"),),
                allowed_capabilities=("shell", "test"),
                backend_allowed_tools=("Read", "Bash"),
                network_access="disabled",
            )
        }
    )

    normalized = client._normalize_request_policy(request)

    assert normalized.execution_policy.readable_roots == (str(tmp_path / "read"),)
    assert normalized.execution_policy.allowed_capabilities == ("shell", "test")


def test_forge_client_persists_capability_adoption_report(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    client = ForgeClient(
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
    )

    path = client.persist_capability_adoption(
        run_id="parent:coding",
        mode="inline",
        report=CapabilityAdoptionReport(
            refreshed=True,
            visible_tool_names=("get_market_ohlcv",),
            capabilities=(
                CapabilityAdoption(
                    tool_name="get_market_ohlcv",
                    service_name="scrivener",
                    adopted=True,
                ),
            ),
        ),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["report"]["capabilities"][0]["tool_name"] == "get_market_ohlcv"
    assert payload["report"]["capabilities"][0]["adopted"] is True
    artifacts = client.get_run_artifacts("parent:coding")
    assert any(artifact.artifact_type == "capability_adoption" for artifact in artifacts)
