from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sophia.agent import AgentConfig, SophiaAgent
from sophia.config import Settings
from sophia.context import ConversationContext
from sophia.events import EventType
from sophia.llm.types import CompletionResponse, Message, Role, StopReason, TokenUsage
from sophia.memory import MemoryManager, MemoryManagerConfig
from sophia.memory.store import InMemoryMemoryStore


class DummyToolDef:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"Tool {name}"

    def to_generic_schema(self) -> dict:
        return {"input_schema": {"type": "object", "properties": {}}}


class DummyPylon:
    def __init__(self) -> None:
        self._tools = [
            DummyToolDef("get_releases_week"),
            DummyToolDef("create_timeseries_chart"),
        ]

    def get_tools(self, only_healthy: bool = True):
        return self._tools

    async def execute_tool(self, name: str, payload: dict):
        return None


class DelegationProvider:
    def __init__(
        self,
        *,
        research_text: str = "Research findings: CPI is decelerating.",
        chart_text: str = "Chart created on canvas.",
        chart_delay_sec: float = 0.0,
    ) -> None:
        self.research_text = research_text
        self.chart_text = chart_text
        self.chart_delay_sec = chart_delay_sec
        self.system_prompts: list[str] = []

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools=None,
        max_tokens: int = 4096,
    ) -> CompletionResponse:
        self.system_prompts.append(system)
        if "SUBAGENT PROFILE: research_worker" in system:
            return CompletionResponse(
                message=Message(role=Role.ASSISTANT, content=self.research_text),
                stop_reason=StopReason.END_TURN,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )
        if "SUBAGENT PROFILE: chart_worker" in system:
            if self.chart_delay_sec > 0:
                await asyncio.sleep(self.chart_delay_sec)
            return CompletionResponse(
                message=Message(role=Role.ASSISTANT, content=self.chart_text),
                stop_reason=StopReason.END_TURN,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content="Supervisor final response"),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )

    async def stream(self, **kwargs):  # pragma: no cover - stream disabled in tests
        raise AssertionError("stream() should not be called in this test")

    async def close(self) -> None:
        return None


def _build_settings(tmp_path: Path, **overrides) -> Settings:
    personality_file = tmp_path / "config" / "personality.md"
    personality_file.parent.mkdir(parents=True, exist_ok=True)
    personality_file.write_text("# Sophia\n\n## Style\nPlain.", encoding="utf-8")
    soul_file = tmp_path / "config" / "soul.md"
    soul_file.write_text("Soul text", encoding="utf-8")
    base = dict(
        personality_path=personality_file,
        soul_path=soul_file,
        lessons_path=tmp_path / "config" / "LESSONS.md",
        skills_enabled=False,
        openai_api_key="test-key",
        llm_model="test-model",
        memory_store_backend="memory",
        subagents_enabled=True,
        subagents_max_parallel_workers=2,
        subagents_default_timeout_sec=0.5,
        subagents_default_max_tool_iterations=2,
        subagents_default_token_budget_chars=2000,
        subagents_default_max_result_chars=300,
        agent_fs_read_allowlist=f"{tmp_path / 'config'},.sophia",
    )
    base.update(overrides)
    return Settings(**base)


def _build_agent(tmp_path: Path, provider: DelegationProvider, **setting_overrides) -> SophiaAgent:
    settings = _build_settings(tmp_path, **setting_overrides)
    return SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=DummyPylon(),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
        memory_manager=MemoryManager(
            store=InMemoryMemoryStore(),
            config=MemoryManagerConfig(enabled=False),
        ),
        canvas_id="canvas-test",
    )


@pytest.mark.asyncio
async def test_subagent_delegation_emits_events_and_merges_context(tmp_path: Path) -> None:
    provider = DelegationProvider()
    agent = _build_agent(tmp_path, provider)
    context = ConversationContext(session_id="session-subagents-ok")

    events = [
        event
        async for event in agent.run(
            "Please research inflation and create a chart of the trend.",
            context,
        )
    ]

    subagent_starts = [e for e in events if e.type == EventType.SUBAGENT_START]
    subagent_ends = [e for e in events if e.type == EventType.SUBAGENT_END]
    subagent_errors = [e for e in events if e.type == EventType.SUBAGENT_ERROR]
    assert len(subagent_starts) == 2
    assert len(subagent_ends) == 2
    assert not subagent_errors
    assert all("run_id" in e.data and "parent_run_id" in e.data for e in subagent_starts)
    assert all(e.data["task_id"] in {"research", "chart"} for e in subagent_starts)
    start_run_ids = {e.data["task_id"]: e.data["run_id"] for e in subagent_starts}
    end_run_ids = {e.data["task_id"]: e.data["run_id"] for e in subagent_ends}
    assert start_run_ids == end_run_ids

    final_messages = [e for e in events if e.type == EventType.MESSAGE_END]
    assert final_messages
    assert final_messages[-1].data["message"].content == "Supervisor final response"
    assert "run_id" in final_messages[-1].data

    parent_prompts = [p for p in provider.system_prompts if "SUBAGENT PROFILE:" not in p]
    assert parent_prompts
    assert "Subagent findings" in parent_prompts[-1]
    assert "research_worker" in parent_prompts[-1]
    assert "chart_worker" in parent_prompts[-1]


@pytest.mark.asyncio
async def test_subagent_timeout_emits_error_event(tmp_path: Path) -> None:
    provider = DelegationProvider(chart_delay_sec=0.2)
    agent = _build_agent(
        tmp_path,
        provider,
        subagents_default_timeout_sec=0.01,
    )
    context = ConversationContext(session_id="session-subagents-timeout")

    events = [
        event
        async for event in agent.run(
            "Research labor market and chart the latest trend.",
            context,
        )
    ]

    timeout_errors = [
        e
        for e in events
        if e.type == EventType.SUBAGENT_ERROR and e.data.get("timed_out") is True
    ]
    assert timeout_errors
    start_run_ids = {
        e.data["task_id"]: e.data["run_id"]
        for e in events
        if e.type == EventType.SUBAGENT_START
    }
    for error_event in timeout_errors:
        assert error_event.data["run_id"] == start_run_ids[error_event.data["task_id"]]


@pytest.mark.asyncio
async def test_subagent_token_budget_emits_error_event(tmp_path: Path) -> None:
    provider = DelegationProvider(
        research_text="This delegated output is intentionally too long for tiny budget limits.",
        chart_text="ok",
    )
    agent = _build_agent(
        tmp_path,
        provider,
        subagents_default_token_budget_chars=12,
    )
    context = ConversationContext(session_id="session-subagents-budget")

    events = [
        event
        async for event in agent.run(
            "Research growth and chart the result.",
            context,
        )
    ]

    budget_errors = [
        e
        for e in events
        if e.type == EventType.SUBAGENT_ERROR and "budget" in e.data.get("error", "").lower()
    ]
    assert budget_errors
    start_run_ids = {
        e.data["task_id"]: e.data["run_id"]
        for e in events
        if e.type == EventType.SUBAGENT_START
    }
    for error_event in budget_errors:
        assert error_event.data["run_id"] == start_run_ids[error_event.data["task_id"]]
