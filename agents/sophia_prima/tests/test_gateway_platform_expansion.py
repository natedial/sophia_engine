from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pylon.tools.base import ToolResult

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
import sophia.gateway.app as gateway_app_module
from sophia.gateway.agent_registry import load_agent_profiles
from sophia.gateway.models import InboundMessage, OutboundMessage
from sophia.gateway.runtime import GatewayRuntime
from sophia.gateway.run_store import GatewayRunStore
from sophia.gateway.skills import GatewaySkillService
from sophia.llm.types import Message, Role, ToolSchema
from sophia.subagents import SubagentOrchestrator, SubagentProfile


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

    assert any(getattr(item, "type", None) == EventType.MESSAGE_END for item in items)
    assert isinstance(items[-1], OutboundMessage)
    assert items[-1].run_id is not None

    record = runtime.get_run_record(items[-1].run_id)
    assert record is not None
    assert record["status"] == "completed"
    assert record["final_text"] == "streamed reply"
    assert len(record["events"]) == 4


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


def test_subagent_planner_adds_quant_and_citation_workers() -> None:
    orchestrator = SubagentOrchestrator(
        profiles={
            "research_worker": SubagentProfile(name="research_worker", instructions=""),
            "quant_worker": SubagentProfile(name="quant_worker", instructions=""),
            "chart_worker": SubagentProfile(name="chart_worker", instructions=""),
            "citation_auditor": SubagentProfile(name="citation_auditor", instructions=""),
            "memory_curator": SubagentProfile(name="memory_curator", instructions=""),
            "dev_worker": SubagentProfile(name="dev_worker", instructions=""),
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


def test_subagent_planner_adds_dev_worker_for_missing_compute_or_scheduler() -> None:
    orchestrator = SubagentOrchestrator(
        profiles={
            "research_worker": SubagentProfile(name="research_worker", instructions=""),
            "quant_worker": SubagentProfile(name="quant_worker", instructions=""),
            "chart_worker": SubagentProfile(name="chart_worker", instructions=""),
            "citation_auditor": SubagentProfile(name="citation_auditor", instructions=""),
            "memory_curator": SubagentProfile(name="memory_curator", instructions=""),
            "dev_worker": SubagentProfile(name="dev_worker", instructions=""),
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

    assert {task.profile_name for task in scheduler_tasks} == {"dev_worker"}
    assert {task.profile_name for task in compute_gap_tasks} == {"dev_worker"}


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
