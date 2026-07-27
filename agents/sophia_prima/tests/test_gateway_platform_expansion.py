from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pylon.tools.base import ToolResult
from sophia_forge.api.main import create_app as create_forge_app
from sophia_forge.config import ForgeSettings
from sophia_forge.core.runtime import ForgeRuntime

import sophia.gateway.app as gateway_app_module
from sophia.agent_profiles import AgentProfile
from sophia.config import Settings
from sophia.events import (
    EventType,
    agent_end,
    agent_start,
    message_end,
    message_start,
    research_plan_created,
)
from sophia.gateway.agent_registry import load_agent_profiles
from sophia.gateway.models import DeliveryArtifact, InboundMessage, OutboundMessage
from sophia.gateway.run_store import GatewayRunStore
from sophia.gateway.runtime import GatewayRuntime
from sophia.gateway.skills import GatewaySkillService
from sophia.llm.types import Message, Role, ToolSchema
from sophia.self_editing import SelfEditChangeRequest, build_self_edit_service
from sophia.subagents import SubagentOrchestrator, SubagentProfile
from sophia_forge_protocol.run_models import RunRequest, RunResult


class StreamingFakeAgent:
    async def run(self, _text, context, *, run_id=None, parent_run_id=None, task_id=None):
        yield agent_start(
            context.session_id,
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        )
        yield message_start(
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        )
        yield message_end(
            Message(role=Role.ASSISTANT, content="streamed reply"),
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        )
        yield agent_end(
            context.session_id,
            run_id=run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        )


@pytest.mark.parametrize(
    ("value", "field_name"),
    [
        ("../admin", "run_id"),
        ("run/../../admin", "run_id"),
        ("%2e%2e%2fadmin", "artifact_id"),
        ("https://example.com", "artifact_id"),
    ],
)
def test_forge_path_segment_rejects_path_injection(
    value: str,
    field_name: str,
) -> None:
    with pytest.raises(ValueError, match=f"invalid {field_name}"):
        gateway_app_module._forge_path_segment(value, field_name=field_name)


def test_forge_path_segment_accepts_generated_identifiers() -> None:
    assert (
        gateway_app_module._forge_path_segment(
            "forge-run_2026.07-001",
            field_name="run_id",
        )
        == "forge-run_2026.07-001"
    )


class AcquisitionFakePylon:
    async def execute_tool(self, name: str, payload: dict):
        if name == "search_series":
            query = str(payload.get("query") or "").lower()
            if "jobless claims" in query or "initial claims" in query:
                return ToolResult.ok(
                    '[{"external_id":"ICSA","title":"Initial Claims","source":"FRED"}]'
                )
            return ToolResult.ok("[]")
        if name == "get_series_info":
            assert payload["series_id"] == "ICSA"
            return ToolResult.ok(
                '{"series_id":"ICSA","title":"Initial Claims","frequency":"weekly","units":"Number"}'
            )
        if name == "get_observations":
            assert payload["series_id"] == "ICSA"
            return ToolResult.ok(
                '{"observations":[{"date":"2026-03-06","value":221000},{"date":"2026-02-27","value":225000}]}'
            )
        raise AssertionError(f"unexpected tool: {name}")


class ExternalIngestionFakePylon:
    def __init__(self) -> None:
        self.ingested = False

    async def execute_tool(self, name: str, payload: dict):
        if name == "search_series":
            query = str(payload.get("query") or "").lower()
            if self.ingested and ("initial claims" in query or "jobless claims" in query):
                return ToolResult.ok(
                    '[{"external_id":"ICSA","title":"Initial Claims","source":"FRED"}]'
                )
            return ToolResult.ok("[]")
        if name == "ingest_series":
            assert payload["source"] == "FRED"
            assert "claims" in str(payload.get("query") or "").lower()
            self.ingested = True
            return ToolResult.ok(
                '{"status":"success","source":"FRED","external_id":"ICSA","selected_candidate":{"external_id":"ICSA","name":"Initial Claims","source":"FRED"}}'
            )
        if name == "get_series_info":
            return ToolResult.ok(
                '{"series_id":"ICSA","title":"Initial Claims","frequency":"weekly","units":"Number"}'
            )
        if name == "get_observations":
            return ToolResult.ok(
                '{"observations":[{"date":"2026-03-06","value":221000},{"date":"2026-02-27","value":225000}]}'
            )
        raise AssertionError(f"unexpected tool: {name}")


@pytest.mark.asyncio
async def test_stream_inbound_persists_events_and_run_record(tmp_path) -> None:
    settings = Settings(gateway_artifact_store_path=tmp_path / "gateway_runs.db")
    runtime = GatewayRuntime(settings=settings)
    runtime._agents[runtime.settings.gateway_default_agent_id] = StreamingFakeAgent()

    items = []
    async for item in runtime.stream_inbound(
        InboundMessage(
            channel="telegram",
            account_id="default",
            peer_id="chat-1",
            text="hello",
        )
    ):
        items.append(item)

    outbounds = [item for item in items if isinstance(item, OutboundMessage)]
    assert len(outbounds) == 2
    assert outbounds[0].delivery_mode == "placeholder"
    assert outbounds[-1].text == "streamed reply"
    assert any(getattr(item, "type", None) == EventType.MESSAGE_END for item in items)
    assert isinstance(items[-1], OutboundMessage)
    assert items[-1].run_id is not None

    record = runtime.get_run_record(items[-1].run_id)
    assert record is not None
    assert record["status"] == "completed"
    assert record["final_text"] == "streamed reply"
    assert any(event["event_type"] == "trace" for event in record["events"])
    assert any(
        event["event_type"] == "trace"
        and event["payload"]["data"].get("stage") == "live_ack_emitted"
        and isinstance(event["payload"]["data"].get("ts"), str)
        for event in record["events"]
    )


@pytest.mark.asyncio
async def test_stream_inbound_persists_research_plan_event(tmp_path) -> None:
    class PlanningFakeAgent:
        async def run(self, _text, context, *, run_id=None, parent_run_id=None, task_id=None):
            yield agent_start(context.session_id, run_id=run_id, parent_run_id=parent_run_id, task_id=task_id)
            yield research_plan_created(
                playbook_id="labor_vs_growth",
                summary="Playbook: labor_vs_growth",
                run_id=run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
            )
            yield agent_end(context.session_id, run_id=run_id, parent_run_id=parent_run_id, task_id=task_id)

    settings = Settings(gateway_artifact_store_path=tmp_path / "gateway_runs.db")
    runtime = GatewayRuntime(settings=settings)
    runtime._agents[runtime.settings.gateway_default_agent_id] = PlanningFakeAgent()

    items = []
    async for item in runtime.stream_inbound(
        InboundMessage(
            channel="telegram",
            account_id="default",
            peer_id="chat-episto",
            text="plan this question",
        )
    ):
        items.append(item)

    outbound = items[-1]
    assert isinstance(outbound, OutboundMessage)
    record = runtime.get_run_record(outbound.run_id)
    assert record is not None
    assert any(
        event["event_type"] == "research_plan_created"
        and event["payload"]["data"]["playbook_id"] == "labor_vs_growth"
        for event in record["events"]
    )
    assert any(
        event["event_type"] == "research_plan_created"
        and "acquisition_decisions" in event["payload"]["data"]
        for event in record["events"]
    )


def test_create_acquisition_job_infers_defaults_from_run_record(tmp_path) -> None:
    settings = Settings(gateway_artifact_store_path=tmp_path / "gateway_runs.db")
    runtime = GatewayRuntime(settings=settings)
    store = runtime._ensure_run_store()
    store.start_run(
        run_id="run-episto",
        session_id="session-episto",
        agent_id="macro_research",
        channel="telegram",
        account_id="research",
        peer_id="desk-1",
        user_id=None,
        message_text="How is the labor market aligning with GDP?",
    )
    store.append_event(
        run_id="run-episto",
        sequence=1,
        event=research_plan_created(
            playbook_id="labor_vs_growth",
            summary="Playbook: labor_vs_growth",
            indicator_families=("real_gdp", "claims"),
            acquisition_decisions=(
                {
                    "indicator_family": "real_gdp",
                    "mode": "none",
                    "source": None,
                    "rationale": "Local series already available.",
                    "retention_target": "canonical",
                },
                {
                    "indicator_family": "claims",
                    "mode": "fetch_now",
                    "source": "FRED",
                    "rationale": "Missing locally but eligible for approved-source acquisition.",
                    "retention_target": "staging",
                },
            ),
        ),
    )
    store.finish_run(run_id="run-episto", status="completed", final_text="pending")

    job = runtime.create_acquisition_job(run_id="run-episto", indicator_family="claims")

    assert job["run_id"] == "run-episto"
    assert job["session_id"] == "session-episto"
    assert job["agent_id"] == "macro_research"
    assert job["playbook_id"] == "labor_vs_growth"
    assert job["requested_source"] == "FRED"
    assert job["mode"] == "fetch_now"
    assert job["retention_target"] == "staging"
    assert job["status"] == "queued"

    record = runtime.get_run_record("run-episto")
    assert record is not None
    assert len(record["acquisition_jobs"]) == 1


@pytest.mark.asyncio
async def test_stream_inbound_persists_diagnostic_fields(tmp_path) -> None:
    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        llm_provider="openai",
    )
    runtime = GatewayRuntime(settings=settings)
    runtime._agents[runtime.settings.gateway_default_agent_id] = StreamingFakeAgent()

    outbound = await runtime.handle_inbound(
        InboundMessage(
            channel="telegram",
            account_id="default",
            peer_id="diag-chat",
            text="hello diagnostics",
        )
    )

    record = runtime.get_run_record(outbound.run_id)
    assert record is not None
    assert record["status"] == "completed"
    assert record["provider_name"] == "openai"
    assert record["outbound_text_len"] == len("streamed reply")


def test_create_acquisition_job_endpoint_round_trip(tmp_path, monkeypatch) -> None:
    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        telegram_polling_enabled=False,
    )

    async def _noop_start(self) -> None:
        self._started = True
        self._startup_error = None

    async def _noop_stop(self) -> None:
        self._started = False

    monkeypatch.setattr(gateway_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "start", _noop_start)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "stop", _noop_stop)

    app = gateway_app_module.create_app()
    with TestClient(app) as client:
        runtime = app.state.runtime
        store = runtime._ensure_run_store()
        store.start_run(
            run_id="run-api",
            session_id="session-api",
            agent_id="macro_research",
            channel="telegram",
            account_id="research",
            peer_id="desk-2",
            user_id=None,
            message_text="How is labor lining up with GDP?",
        )
        store.append_event(
            run_id="run-api",
            sequence=1,
            event=research_plan_created(
                playbook_id="labor_vs_growth",
                summary="Playbook: labor_vs_growth",
                indicator_families=("claims",),
                acquisition_decisions=(
                    {
                        "indicator_family": "claims",
                        "mode": "fetch_now",
                        "source": "FRED",
                        "rationale": "Missing locally but eligible for approved-source acquisition.",
                        "retention_target": "staging",
                    },
                ),
            ),
        )
        store.finish_run(run_id="run-api", status="completed", final_text="pending")

        create_response = client.post(
            "/v1/acquisition-jobs",
            json={
                "run_id": "run-api",
                "indicator_family": "claims",
            },
        )
        assert create_response.status_code == 200
        job = create_response.json()
        assert job["run_id"] == "run-api"
        assert job["requested_source"] == "FRED"
        assert job["mode"] == "fetch_now"

        get_response = client.get(f"/v1/acquisition-jobs/{job['job_id']}")
        assert get_response.status_code == 200
        assert get_response.json()["indicator_family"] == "claims"


@pytest.mark.asyncio
async def test_execute_acquisition_job_materializes_artifact(tmp_path) -> None:
    settings = Settings(gateway_artifact_store_path=tmp_path / "gateway_runs.db")
    runtime = GatewayRuntime(settings=settings)
    runtime._pylon = AcquisitionFakePylon()
    store = runtime._ensure_run_store()
    store.start_run(
        run_id="run-exec",
        session_id="session-exec",
        agent_id="macro_research",
        channel="telegram",
        account_id="research",
        peer_id="desk-3",
        user_id=None,
        message_text="labor vs growth",
    )
    store.append_event(
        run_id="run-exec",
        sequence=1,
        event=research_plan_created(
            playbook_id="labor_vs_growth",
            summary="Playbook: labor_vs_growth",
            indicator_families=("claims",),
            indicator_queries=(
                {
                    "indicator_family": "claims",
                    "queries": ("initial claims", "jobless claims"),
                    "preferred_sources": ("FRED",),
                },
            ),
            acquisition_decisions=(
                {
                    "indicator_family": "claims",
                    "mode": "fetch_now",
                    "source": "FRED",
                    "rationale": "Missing locally but eligible for approved-source acquisition.",
                    "retention_target": "staging",
                },
            ),
        ),
    )
    store.finish_run(run_id="run-exec", status="completed", final_text="pending")
    job = runtime.create_acquisition_job(run_id="run-exec", indicator_family="claims")

    result = await runtime.execute_acquisition_job(job_id=job["job_id"], observation_days=30)

    assert result["status"] == "completed"
    assert result["artifacts"]
    artifact = result["artifacts"][-1]
    assert artifact["stage"] == "materialization"
    assert artifact["payload"]["series_id"] == "ICSA"
    assert artifact["payload"]["validation"]["observations_found"] is True


@pytest.mark.asyncio
async def test_execute_acquisition_job_can_handoff_to_ingestion_backend(tmp_path) -> None:
    settings = Settings(gateway_artifact_store_path=tmp_path / "gateway_runs.db")
    runtime = GatewayRuntime(settings=settings)
    runtime._pylon = ExternalIngestionFakePylon()
    store = runtime._ensure_run_store()
    store.start_run(
        run_id="run-external",
        session_id="session-external",
        agent_id="macro_research",
        channel="telegram",
        account_id="research",
        peer_id="desk-5",
        user_id=None,
        message_text="labor vs growth",
    )
    store.append_event(
        run_id="run-external",
        sequence=1,
        event=research_plan_created(
            playbook_id="labor_vs_growth",
            summary="Playbook: labor_vs_growth",
            indicator_families=("claims",),
            indicator_queries=(
                {
                    "indicator_family": "claims",
                    "queries": ("initial claims", "jobless claims"),
                    "preferred_sources": ("FRED",),
                },
            ),
            acquisition_decisions=(
                {
                    "indicator_family": "claims",
                    "mode": "fetch_now",
                    "source": "FRED",
                    "rationale": "Missing locally but eligible for approved-source acquisition.",
                    "retention_target": "staging",
                },
            ),
        ),
    )
    store.finish_run(run_id="run-external", status="completed", final_text="pending")
    job = runtime.create_acquisition_job(run_id="run-external", indicator_family="claims")

    result = await runtime.execute_acquisition_job(job_id=job["job_id"], observation_days=30)

    assert result["status"] == "completed"
    artifact = result["artifacts"][-1]
    assert artifact["payload"]["ingestion_result"]["status"] == "success"
    assert artifact["payload"]["series_id"] == "ICSA"


def test_execute_acquisition_job_endpoint_round_trip(tmp_path, monkeypatch) -> None:
    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        telegram_polling_enabled=False,
    )

    async def _noop_start(self) -> None:
        self._started = True
        self._startup_error = None

    async def _noop_stop(self) -> None:
        self._started = False

    monkeypatch.setattr(gateway_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "start", _noop_start)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "stop", _noop_stop)

    app = gateway_app_module.create_app()
    with TestClient(app) as client:
        runtime = app.state.runtime
        runtime._pylon = AcquisitionFakePylon()
        store = runtime._ensure_run_store()
        store.start_run(
            run_id="run-api-exec",
            session_id="session-api-exec",
            agent_id="macro_research",
            channel="telegram",
            account_id="research",
            peer_id="desk-4",
            user_id=None,
            message_text="labor vs growth",
        )
        store.append_event(
            run_id="run-api-exec",
            sequence=1,
            event=research_plan_created(
                playbook_id="labor_vs_growth",
                summary="Playbook: labor_vs_growth",
                indicator_families=("claims",),
                indicator_queries=(
                    {
                        "indicator_family": "claims",
                        "queries": ("initial claims", "jobless claims"),
                        "preferred_sources": ("FRED",),
                    },
                ),
                acquisition_decisions=(
                    {
                        "indicator_family": "claims",
                        "mode": "fetch_now",
                        "source": "FRED",
                        "rationale": "Missing locally but eligible for approved-source acquisition.",
                        "retention_target": "staging",
                    },
                ),
            ),
        )
        store.finish_run(run_id="run-api-exec", status="completed", final_text="pending")
        job = runtime.create_acquisition_job(run_id="run-api-exec", indicator_family="claims")

        response = client.post(
            f"/v1/acquisition-jobs/{job['job_id']}/execute",
            json={"observation_days": 30},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["artifacts"][-1]["payload"]["series_id"] == "ICSA"


def test_dashboard_admin_endpoints_round_trip(tmp_path, monkeypatch) -> None:
    presentation_root = tmp_path / "config" / "presentation"
    channels_path = presentation_root / "channels"
    rendering_path = presentation_root / "rendering"
    artifact_dir = tmp_path / ".sophia" / "presentation"
    channels_path.mkdir(parents=True, exist_ok=True)
    rendering_path.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    core_path = presentation_root / "core.md"
    communication_preferences_path = presentation_root / "communication_preferences.json"
    core_path.write_text("# Core\n\n- Preserve fidelity.\n", encoding="utf-8")
    (channels_path / "web.json").write_text(
        '{"channel":"web","supports_markdown_tables":true,"supports_image_attachments":true,'
        '"supports_document_attachments":true,"max_text_chars":12000,'
        '"preferred_structured_delivery":{"table":"text"}}\n',
        encoding="utf-8",
    )
    communication_preferences_path.write_text(
        '{"big_picture_vs_brevity":"full_picture","verbose_vs_terse":"terse",'
        '"precision_vs_approximation":"precision","structured_vs_narrative":"structured",'
        '"proactive_vs_reactive":"proactive","decisive_vs_caveated":"caveated"}\n',
        encoding="utf-8",
    )
    (rendering_path / "png_table_theme.json").write_text(
        '{"font_family":"mono","title_font_size":24,"body_font_size":18,"line_height":28,'
        '"margin":32,"char_width":10.6,"corner_radius":20,"background_start":"#000000",'
        '"background_end":"#111111","panel_fill":"#222222","panel_stroke":"#333333",'
        '"accent":"#44aaee","title_color":"#ffffff","header_color":"#dddddd",'
        '"text_color":"#cccccc","divider_color":"#555555","shadow_color":"#101010",'
        '"header_fill":"#161616"}\n',
        encoding="utf-8",
    )

    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        telegram_polling_enabled=False,
        openai_api_key="openai-secret",
        deepinfra_api_key="deepinfra-secret",
        presentation_core_path=core_path,
        presentation_channels_path=channels_path,
        presentation_rendering_path=rendering_path,
        presentation_artifact_dir=artifact_dir,
    )

    async def _noop_start(self) -> None:
        self._started = True
        self._startup_error = None

    async def _noop_stop(self) -> None:
        self._started = False

    monkeypatch.setattr(gateway_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "start", _noop_start)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "stop", _noop_stop)

    app = gateway_app_module.create_app()
    with TestClient(app) as client:
        runtime = app.state.runtime
        store = runtime._ensure_run_store()
        store.start_run(
            run_id="run-dashboard",
            session_id="session-dashboard",
            agent_id="sophia_prima",
            channel="web",
            account_id="default",
            peer_id="desk-dashboard",
            user_id=None,
            message_text="render this table",
        )
        store.finish_run(run_id="run-dashboard", status="completed", final_text="attached")

        artifact_path = artifact_dir / "run-dashboard_table.svg"
        artifact_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><text>hello</text></svg>',
            encoding="utf-8",
        )
        artifact_id = store.save_skill_artifact(
            skill_name="presentation-delivery",
            run_id="run-dashboard",
            session_id="session-dashboard",
            agent_id="sophia_prima",
            payload={
                "kind": "document",
                "mime_type": "image/svg+xml",
                "path": str(artifact_path),
                "channel": "web",
            },
        )

        runs_response = client.get("/v1/dashboard/runs?limit=10")
        assert runs_response.status_code == 200
        runs = runs_response.json()["runs"]
        assert runs[0]["run_id"] == "run-dashboard"
        assert runs[0]["skill_artifact_count"] == 1

        components_response = client.get("/v1/dashboard/components")
        assert components_response.status_code == 200
        components = components_response.json()["components"]
        component_ids = {component["component_id"] for component in components}
        assert "sophia_prima" in component_ids
        assert "scrivener" in component_ids
        prima = next(component for component in components if component["component_id"] == "sophia_prima")
        assert prima["category"] == "llm"
        assert prima["model_name"] == settings.llm_model

        llm_catalog_response = client.get("/v1/dashboard/llm/catalog")
        assert llm_catalog_response.status_code == 200
        llm_catalog = llm_catalog_response.json()
        assert llm_catalog["current_model_spec"] == "openai:gpt-4.1-mini"
        assert any(
            model["model_spec"] == "deepinfra:MiniMaxAI/MiniMax-M2.5"
            for model in llm_catalog["models"]
        )

        llm_selection_response = client.put(
            "/v1/dashboard/llm/selection",
            json={"model_spec": "deepinfra:MiniMaxAI/MiniMax-M2.5"},
        )
        assert llm_selection_response.status_code == 200
        updated_catalog = llm_selection_response.json()
        assert updated_catalog["current_model_spec"] == "deepinfra:MiniMaxAI/MiniMax-M2.5"
        assert settings.llm_model == "deepinfra:MiniMaxAI/MiniMax-M2.5"

        run_response = client.get("/v1/runs/run-dashboard")
        assert run_response.status_code == 200
        assert run_response.json()["skill_artifacts"][0]["artifact_id"] == artifact_id

        presentation_response = client.get("/v1/dashboard/presentation")
        assert presentation_response.status_code == 200
        assert "Preserve fidelity" in presentation_response.json()["core_guidance"]
        assert (
            presentation_response.json()["communication_preferences"]["big_picture_vs_brevity"]
            == "full_picture"
        )

        core_update = client.put(
            "/v1/dashboard/presentation/core",
            json={"content": "# Core\n\n- Prefer concise delivery."},
        )
        assert core_update.status_code == 200
        assert "Prefer concise delivery" in core_path.read_text(encoding="utf-8")

        channel_update = client.put(
            "/v1/dashboard/presentation/channels/web",
            json={
                "supports_markdown_tables": False,
                "supports_image_attachments": True,
                "supports_document_attachments": True,
                "max_text_chars": 9000,
                "preferred_structured_delivery": {"table": "image", "chart": "image"},
            },
        )
        assert channel_update.status_code == 200
        assert '"table": "image"' in (channels_path / "web.json").read_text(encoding="utf-8")

        theme_update = client.put(
            "/v1/dashboard/presentation/rendering/theme",
            json={
                "font_family": "mono",
                "title_font_size": 26,
                "body_font_size": 17,
                "line_height": 27,
                "margin": 30,
                "char_width": 10.2,
                "corner_radius": 18,
                "background_start": "#020617",
                "background_end": "#0f172a",
                "panel_fill": "#111827",
                "panel_stroke": "#334155",
                "accent": "#22d3ee",
                "title_color": "#f8fafc",
                "header_color": "#bae6fd",
                "text_color": "#e2e8f0",
                "divider_color": "#475569",
                "shadow_color": "#020617",
                "header_fill": "#0b1120",
            },
        )
        assert theme_update.status_code == 200
        assert '"accent": "#22d3ee"' in (
            rendering_path / "png_table_theme.json"
        ).read_text(encoding="utf-8")

        preferences_update = client.put(
            "/v1/dashboard/presentation/preferences",
            json={
                "big_picture_vs_brevity": "brevity",
                "verbose_vs_terse": "verbose",
                "precision_vs_approximation": "approximation",
                "structured_vs_narrative": "narrative",
                "proactive_vs_reactive": "reactive",
                "decisive_vs_caveated": "decisive",
            },
        )
        assert preferences_update.status_code == 200
        assert '"verbose_vs_terse": "verbose"' in communication_preferences_path.read_text(
            encoding="utf-8"
        )

        artifact_response = client.get(f"/v1/dashboard/artifacts/{artifact_id}/content")
        assert artifact_response.status_code == 200
        assert "<text>hello</text>" in artifact_response.text


def test_dashboard_proposal_review_endpoints_round_trip(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    skills_dir = tmp_path / "skills"
    proposal_dir = tmp_path / ".sophia" / "self_edit_proposals"
    config_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    proposal_dir.parent.mkdir(parents=True, exist_ok=True)
    (config_dir / "personality.md").write_text("# Sophia\n\n## Style\nPlain.\n", encoding="utf-8")
    (config_dir / "soul.md").write_text("Soul text\n", encoding="utf-8")
    (config_dir / "LESSONS.md").write_text("- Verify dates.\n", encoding="utf-8")

    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        telegram_polling_enabled=False,
        personality_path=config_dir / "personality.md",
        soul_path=config_dir / "soul.md",
        lessons_path=config_dir / "LESSONS.md",
        skills_path=skills_dir,
        self_edit_proposal_dir=proposal_dir,
        agent_fs_read_allowlist=",".join(
            [str(config_dir), str(skills_dir), str(proposal_dir.parent)]
        ),
        agent_fs_write_allowlist=str(proposal_dir.parent),
    )

    async def _noop_start(self) -> None:
        self._started = True
        self._startup_error = None

    async def _noop_stop(self) -> None:
        self._started = False

    monkeypatch.setattr(gateway_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "start", _noop_start)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "stop", _noop_stop)

    service = build_self_edit_service(settings=settings)
    proposal = service.create_proposal(
        title="Tighten lesson wording",
        rationale="Shorten the reminder and make it more direct.",
        changes=[
            SelfEditChangeRequest(
                target_path="config/LESSONS.md",
                updated_content="- Verify dates.\n- State key assumptions.\n",
                summary="Add an assumptions reminder.",
            )
        ],
        source_agent_id="sophia_prima",
        source_run_id="run-proposal-1",
        source_session_id="session-proposal-1",
    )

    app = gateway_app_module.create_app()
    with TestClient(app) as client:
        list_response = client.get("/v1/dashboard/proposals?status=pending")
        assert list_response.status_code == 200
        proposals = list_response.json()["proposals"]
        assert proposals[0]["proposal_id"] == proposal.proposal_id
        assert proposals[0]["change_count"] == 1

        detail_response = client.get(f"/v1/dashboard/proposals/{proposal.proposal_id}")
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert "--- config/LESSONS.md" in detail_payload["patch_text"]
        assert detail_payload["changes"][0]["target_path"] == "config/LESSONS.md"

        review_response = client.post(
            f"/v1/dashboard/proposals/{proposal.proposal_id}/review",
            json={
                "status": "approved",
                "actor": "dashboard",
                "reason": "Ready for acceptance.",
            },
        )
        assert review_response.status_code == 200
        assert review_response.json()["status"] == "approved"

        approved_detail = client.get(f"/v1/dashboard/proposals/{proposal.proposal_id}")
        assert approved_detail.status_code == 200
        assert approved_detail.json()["review_actor"] == "dashboard"


def test_dashboard_forge_promotion_endpoints_round_trip(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    import subprocess

    subprocess.run(["git", "init", str(repo_root)], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "forge-tests@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "Forge Tests"],
        check=True,
        capture_output=True,
        text=True,
    )
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
    subprocess.run(
        ["git", "-C", str(repo_root), "branch", "-M", "main"],
        check=True,
        capture_output=True,
        text=True,
    )

    async def _draft_pr_executor(request: RunRequest) -> RunResult:
        file_path = Path(request.workspace_root) / "services" / "foo" / "tool.py"
        file_path.write_text("def run():\n    return False\n", encoding="utf-8")
        return RunResult(
            run_id=request.run_id,
            status="completed",
            summary="Updated the tool implementation.",
            changed_files=("services/foo/tool.py",),
        )

    forge_runtime = ForgeRuntime(
        settings=ForgeSettings(
            store_path=tmp_path / "forge_runs.db",
            output_dir=tmp_path / "forge_runs",
        ),
        executor=_draft_pr_executor,
    )
    forge_app = create_forge_app(runtime=forge_runtime)
    real_async_client = httpx.AsyncClient

    def _forge_async_client(*_args, **kwargs):
        return real_async_client(
            transport=httpx.ASGITransport(app=forge_app),
            base_url="http://forge-test",
            timeout=kwargs.get("timeout"),
        )

    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        telegram_polling_enabled=False,
        forge_base_url="http://forge-test",
        forge_request_timeout_sec=2.0,
    )

    async def _noop_start(self) -> None:
        self._started = True
        self._startup_error = None

    async def _noop_stop(self) -> None:
        self._started = False

    monkeypatch.setattr(gateway_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "start", _noop_start)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "stop", _noop_stop)
    monkeypatch.setattr(gateway_app_module.httpx, "AsyncClient", _forge_async_client)

    forge_client = TestClient(forge_app)
    create_response = forge_client.post(
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
    assert create_response.status_code == 200
    forge_run_id = create_response.json()["run_id"]
    latest = forge_client.get(f"/v1/runs/{forge_run_id}").json()
    while latest["status"] in {"queued", "running"}:
        latest = forge_client.get(f"/v1/runs/{forge_run_id}").json()

    app = gateway_app_module.create_app()
    with TestClient(app) as client:
        promotions_response = client.get("/v1/dashboard/forge/promotions?limit=10")
        assert promotions_response.status_code == 200
        runs = promotions_response.json()["runs"]
        assert runs[0]["run_id"] == forge_run_id
        assert runs[0]["promotion_mode"] == "draft_pr"

        detail_response = client.get(f"/v1/dashboard/forge/promotions/{forge_run_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["content"]["pr_request"]["mode"] == "draft_pr"
        assert detail["content"]["promotion_status"]["status"] == "prepared"
        patch_artifact = next(
            artifact for artifact in detail["artifacts"] if artifact["artifact_type"] == "pr_request"
        )
        artifact_content = client.get(
            f"/v1/dashboard/forge/promotions/{forge_run_id}/artifacts/{patch_artifact['artifact_id']}/content"
        )
        assert artifact_content.status_code == 200
        assert artifact_content.json()["mode"] == "draft_pr"

        publish_response = client.post(
            f"/v1/dashboard/forge/promotions/{forge_run_id}/publish"
        )
        assert publish_response.status_code == 200
        assert publish_response.json()["mode"] == "draft_pr"


@pytest.mark.asyncio
async def test_handle_inbound_routes_to_specialist_agent(tmp_path) -> None:
    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        gateway_bindings_json=(
            '[{"channel":"telegram","account_id":"research","agent_id":"macro_research"}]'
        ),
    )
    runtime = GatewayRuntime(settings=settings)
    runtime._agents["macro_research"] = SimpleNamespace(
        chat=lambda *_args, **_kwargs: None
    )

    async def _chat(_text, _context):
        return SimpleNamespace(content="research-specialist")

    runtime._agents["macro_research"].chat = _chat

    outbound = await runtime.handle_inbound(
        InboundMessage(
            channel="telegram",
            account_id="research",
            peer_id="desk-7",
            text="what matters today?",
        )
    )

    assert outbound.agent_id == "macro_research"
    assert outbound.text == "research-specialist"


def test_load_agent_profiles_includes_specialists() -> None:
    profiles = load_agent_profiles(
        default_agent_id="sophia_prima",
        raw_profiles_json="",
    )

    assert set(profiles) >= {
        "sophia_prima",
        "macro_research",
        "trader_workbench",
        "canvas_analyst",
    }
    assert profiles["macro_research"].tool_allowlist is not None
    assert "search_web" in profiles["macro_research"].tool_allowlist
    assert "get_web_context" in profiles["macro_research"].tool_allowlist


def test_subagent_planner_adds_quant_and_citation_workers() -> None:
    orchestrator = SubagentOrchestrator(
        profiles={
            "research_worker": SubagentProfile(name="research_worker", instructions=""),
            "quant_worker": SubagentProfile(name="quant_worker", instructions=""),
            "chart_worker": SubagentProfile(name="chart_worker", instructions=""),
            "citation_auditor": SubagentProfile(name="citation_auditor", instructions=""),
            "memory_curator": SubagentProfile(name="memory_curator", instructions=""),
            "coding_worker": SubagentProfile(name="coding_worker", instructions=""),
        },
        max_parallel_workers=2,
    )
    tools = [
        ToolSchema(name="compute", description="", input_schema={}),
        ToolSchema(name="search_research", description="", input_schema={}),
        ToolSchema(name="get_observations", description="", input_schema={}),
    ]

    tasks = orchestrator.plan_for_message(
        message="Compute a regression and audit the sources for this claim.",
        available_tools=tools,
        canvas_id=None,
    )

    assert {task.profile_name for task in tasks} == {"quant_worker", "citation_auditor"}


def test_subagent_planner_adds_coding_worker_for_missing_compute_or_scheduler() -> None:
    orchestrator = SubagentOrchestrator(
        profiles={
            "research_worker": SubagentProfile(name="research_worker", instructions=""),
            "quant_worker": SubagentProfile(name="quant_worker", instructions=""),
            "chart_worker": SubagentProfile(name="chart_worker", instructions=""),
            "citation_auditor": SubagentProfile(name="citation_auditor", instructions=""),
            "memory_curator": SubagentProfile(name="memory_curator", instructions=""),
            "coding_worker": SubagentProfile(name="coding_worker", instructions=""),
        },
        max_parallel_workers=2,
    )

    scheduler_tasks = orchestrator.plan_for_message(
        message="Build a scheduler for nightly sync jobs.",
        available_tools=[],
        canvas_id=None,
    )
    compute_gap_tasks = orchestrator.plan_for_message(
        message="Compute a regression for this request.",
        available_tools=[ToolSchema(name="get_observations", description="", input_schema={})],
        canvas_id=None,
    )

    assert {task.profile_name for task in scheduler_tasks} == {"coding_worker"}
    assert {task.profile_name for task in compute_gap_tasks} == {"coding_worker"}


def test_subagent_planner_adds_coding_worker_for_explicit_repo_write_requests() -> None:
    orchestrator = SubagentOrchestrator(
        profiles={
            "research_worker": SubagentProfile(name="research_worker", instructions=""),
            "quant_worker": SubagentProfile(name="quant_worker", instructions=""),
            "chart_worker": SubagentProfile(name="chart_worker", instructions=""),
            "citation_auditor": SubagentProfile(name="citation_auditor", instructions=""),
            "memory_curator": SubagentProfile(name="memory_curator", instructions=""),
            "coding_worker": SubagentProfile(name="coding_worker", instructions=""),
        },
        max_parallel_workers=2,
    )

    tasks = orchestrator.plan_for_message(
        message="Please write this into our codebase and open a PR.",
        available_tools=[],
        canvas_id=None,
    )

    assert {task.profile_name for task in tasks} == {"coding_worker"}


def test_subagent_planner_adds_coding_worker_for_tool_build_and_deploy_requests() -> None:
    orchestrator = SubagentOrchestrator(
        profiles={
            "research_worker": SubagentProfile(name="research_worker", instructions=""),
            "quant_worker": SubagentProfile(name="quant_worker", instructions=""),
            "chart_worker": SubagentProfile(name="chart_worker", instructions=""),
            "citation_auditor": SubagentProfile(name="citation_auditor", instructions=""),
            "memory_curator": SubagentProfile(name="memory_curator", instructions=""),
            "coding_worker": SubagentProfile(name="coding_worker", instructions=""),
        },
        max_parallel_workers=2,
    )

    tasks = orchestrator.plan_for_message(
        message="Build and deploy a Telegram delivery tool for long-form reports.",
        available_tools=[],
        canvas_id=None,
    )

    assert {task.profile_name for task in tasks} == {"coding_worker"}


@pytest.mark.asyncio
async def test_gateway_skill_service_generates_artifacts(tmp_path) -> None:
    class FakePylon:
        async def execute_tool(self, name: str, payload: dict):
            assert name == "get_releases_upcoming"
            assert payload["days"] >= 1
            return ToolResult.ok(
                '[{"release_id": 10, "name": "Consumer Price Index", "release_date": "2026-02-24T13:30:00Z"}]'
            )

    store = GatewayRunStore(tmp_path / "gateway_runs.db")
    service = GatewaySkillService(pylon=FakePylon(), run_store=store)

    result = await service.run_catalyst_radar(
        window_hours=72,
        portfolio_profile={"focus_assets": ["rates", "usd"]},
        include={"economic_releases": True},
        max_events=10,
        as_of="2026-02-23T13:30:00Z",
        session_id="session-1",
        agent_id="trader_workbench",
        run_id="run-1",
    )

    assert result["events"]
    assert result["artifact_id"].startswith("artifact_")


def test_post_message_returns_delivery_artifacts(tmp_path, monkeypatch) -> None:
    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        telegram_polling_enabled=False,
    )

    async def _noop_start(self) -> None:
        self._started = True
        self._startup_error = None

    async def _noop_stop(self) -> None:
        self._started = False

    monkeypatch.setattr(gateway_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "start", _noop_start)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "stop", _noop_stop)

    app = gateway_app_module.create_app()
    with TestClient(app) as client:
        runtime = app.state.runtime

        async def fake_handle_inbound(_message: InboundMessage) -> OutboundMessage:
            return OutboundMessage(
                text="I attached the chart.",
                session_id="session-artifacts",
                agent_id="macro_research",
                channel="web",
                account_id="default",
                peer_id="dashboard-user",
                run_id="run-artifacts",
                delivery_mode="image",
                artifacts=(
                    DeliveryArtifact(
                        artifact_id="artifact_chart_001",
                        kind="image",
                        mime_type="image/png",
                        path="/tmp/run-artifacts/chart.png",
                        caption="Forecast chart",
                    ),
                ),
            )

        runtime.handle_inbound = fake_handle_inbound

        response = client.post(
            "/v1/messages",
            json={
                "channel": "web",
                "account_id": "default",
                "peer_id": "dashboard-user",
                "text": "Show me the chart",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["delivery_mode"] == "image"
        assert payload["artifacts"] == [
            {
                "artifact_id": "artifact_chart_001",
                "kind": "image",
                "mime_type": "image/png",
                "path": "/tmp/run-artifacts/chart.png",
                "caption": "Forecast chart",
            }
        ]


def test_websocket_stream_returns_delivery_artifacts(tmp_path, monkeypatch) -> None:
    settings = Settings(
        gateway_artifact_store_path=tmp_path / "gateway_runs.db",
        telegram_polling_enabled=False,
    )

    async def _noop_start(self) -> None:
        self._started = True
        self._startup_error = None

    async def _noop_stop(self) -> None:
        self._started = False

    monkeypatch.setattr(gateway_app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "start", _noop_start)
    monkeypatch.setattr(gateway_app_module.GatewayRuntime, "stop", _noop_stop)

    app = gateway_app_module.create_app()
    with TestClient(app) as client:
        runtime = app.state.runtime

        async def fake_stream_inbound(_message: InboundMessage):
            yield OutboundMessage(
                text="I attached the chart.",
                session_id="session-stream-artifacts",
                agent_id="macro_research",
                channel="web",
                account_id="default",
                peer_id="dashboard-user",
                run_id="run-stream-artifacts",
                delivery_mode="image",
                artifacts=(
                    DeliveryArtifact(
                        artifact_id="artifact_chart_002",
                        kind="image",
                        mime_type="image/png",
                        path="/tmp/run-stream-artifacts/chart.png",
                        caption=None,
                    ),
                ),
            )

        runtime.stream_inbound = fake_stream_inbound

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "connect"})
            assert websocket.receive_json()["type"] == "connected"

            websocket.send_json(
                {
                    "type": "stream_inbound_message",
                    "payload": {
                        "channel": "web",
                        "account_id": "default",
                        "peer_id": "dashboard-user",
                        "text": "Show me the chart",
                    },
                }
            )

            frame = websocket.receive_json()
            assert frame["type"] == "outbound_message"
            assert frame["payload"]["delivery_mode"] == "image"
            assert frame["payload"]["artifacts"] == [
                {
                    "artifact_id": "artifact_chart_002",
                    "kind": "image",
                    "mime_type": "image/png",
                    "path": "/tmp/run-stream-artifacts/chart.png",
                    "caption": None,
                }
            ]
