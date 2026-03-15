from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sophia.agent import AgentConfig, SophiaAgent
from sophia.config import Settings
from sophia.context import ConversationContext
from sophia.events import EventType
from sophia.episto_adapter import EpistoPlanContext
from sophia.llm.types import CompletionResponse, Message, Role, StopReason, TokenUsage
from sophia.memory import MemoryManager, MemoryManagerConfig
from sophia.memory.store import InMemoryMemoryStore


class DummyToolResult:
    def __init__(self, payload: list[dict] | None = None) -> None:
        self.success = True
        self._payload = payload or []

    def to_content(self) -> str:
        import json

        return json.dumps(self._payload)


class DummyProvider:
    def __init__(self) -> None:
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
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content="ok"),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )

    async def stream(self, **kwargs):  # pragma: no cover - stream disabled in tests
        raise AssertionError("stream() should not be called in this test")

    async def close(self) -> None:
        return None


class DummyPylon:
    def get_tools(self, only_healthy: bool = True):
        return [
            SimpleNamespace(
                name="search_series",
                description="search",
                to_generic_schema=lambda: {"input_schema": {"type": "object"}},
            ),
            SimpleNamespace(
                name="get_series_info",
                description="info",
                to_generic_schema=lambda: {"input_schema": {"type": "object"}},
            ),
            SimpleNamespace(
                name="get_observations",
                description="obs",
                to_generic_schema=lambda: {"input_schema": {"type": "object"}},
            ),
        ]

    async def execute_tool(self, name: str, payload: dict):
        if name == "search_series":
            query = str(payload.get("query") or "").lower()
            if "gdp" in query:
                return DummyToolResult(
                    [{"external_id": "GDPC1", "source": "FRED"}]
                )
            if "payroll" in query:
                return DummyToolResult(
                    [{"external_id": "PAYEMS", "source": "FRED"}]
                )
            if "unemployment" in query:
                return DummyToolResult(
                    [{"external_id": "UNRATE", "source": "FRED"}]
                )
            if "job openings" in query or "jolts openings" in query:
                return DummyToolResult(
                    [{"external_id": "JTSJOL", "source": "BLS"}]
                )
            return DummyToolResult([])
        raise AssertionError("No tool execution expected in this test")


def _build_agent(tmp_path: Path) -> tuple[SophiaAgent, DummyProvider]:
    personality_file = tmp_path / "config" / "personality.md"
    personality_file.parent.mkdir(parents=True)
    personality_file.write_text("# Sophia\n\n## Style\nPlain.", encoding="utf-8")

    soul_file = tmp_path / "config" / "soul.md"
    soul_file.write_text("Soul text", encoding="utf-8")

    settings = Settings(
        personality_path=personality_file,
        soul_path=soul_file,
        lessons_path=tmp_path / "config" / "LESSONS.md",
        skills_enabled=False,
        openai_api_key="test-key",
        llm_model="test-model",
        memory_store_backend="memory",
        agent_fs_read_allowlist=f"{tmp_path / 'config'},.sophia",
    )
    provider = DummyProvider()
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=DummyPylon(),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
        memory_manager=MemoryManager(
            store=InMemoryMemoryStore(),
            config=MemoryManagerConfig(enabled=False),
        ),
    )
    return agent, provider


@pytest.mark.asyncio
async def test_agent_injects_episto_research_plan_when_available(tmp_path: Path) -> None:
    agent, provider = _build_agent(tmp_path)
    context = ConversationContext(session_id="episto-test")

    await agent.chat(
        "How is the labor market aligning with the GDP strength of the past few quarters?",
        context,
    )

    assert provider.system_prompts
    assert "Research plan" in provider.system_prompts[0]
    assert "Playbook: labor_vs_growth" in provider.system_prompts[0]
    assert "Time series policy" in provider.system_prompts[0]
    assert "get_series_info" in provider.system_prompts[0]


@pytest.mark.asyncio
async def test_agent_skips_episto_context_when_adapter_returns_none(tmp_path: Path) -> None:
    agent, provider = _build_agent(tmp_path)
    context = ConversationContext(session_id="episto-test-none")

    class NoOpEpisto:
        async def plan(self, _question: str):
            return None

    agent.episto = NoOpEpisto()

    await agent.chat("hello there", context)

    assert provider.system_prompts
    assert "Research plan" not in provider.system_prompts[0]


@pytest.mark.asyncio
async def test_agent_uses_manual_episto_plan_context(tmp_path: Path) -> None:
    agent, provider = _build_agent(tmp_path)
    context = ConversationContext(session_id="episto-test-manual")

    class ManualEpisto:
        async def plan(self, _question: str):
            return EpistoPlanContext(
                playbook_id="custom",
                summary="Playbook: custom\nSubquestions:\n- test",
            )

    agent.episto = ManualEpisto()

    await agent.chat("custom economic question", context)

    assert provider.system_prompts
    assert "Playbook: custom" in provider.system_prompts[0]


@pytest.mark.asyncio
async def test_agent_emits_research_plan_event(tmp_path: Path) -> None:
    agent, _provider = _build_agent(tmp_path)
    context = ConversationContext(session_id="episto-test-event")

    events = [
        event
        async for event in agent.run(
            "How is the labor market aligning with the GDP strength of the past few quarters?",
            context,
        )
    ]

    plan_events = [event for event in events if event.type == EventType.RESEARCH_PLAN_CREATED]

    assert len(plan_events) == 1
    assert plan_events[0].data["playbook_id"] == "labor_vs_growth"
    assert "Indicator families" in plan_events[0].data["summary"]
    assert "Capability status" in plan_events[0].data["summary"]
    assert "Acquisition decisions" in plan_events[0].data["summary"]
    assert "real_gdp" in plan_events[0].data["indicator_families"]
    assert any(
        item["indicator_family"] == "real_gdp"
        and "real gdp" in item["queries"]
        for item in plan_events[0].data["indicator_queries"]
    )
    assert any(
        item["indicator_family"] == "real_gdp" and item["available_locally"] is True
        for item in plan_events[0].data["capability_checks"]
    )
    assert any(
        item["indicator_family"] == "claims"
        and item["mode"] == "fetch_now"
        and item["handling_mode"] == "acquire_and_store"
        for item in plan_events[0].data["acquisition_decisions"]
    )
