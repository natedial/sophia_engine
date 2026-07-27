from __future__ import annotations

from sophia.agent_profiles import AgentProfile
from sophia.agent import SophiaAgent
from sophia.context import ConversationContext
from sophia.llm.types import ToolSchema
from sophia.personality.loader import Personality
from sophia_forge_protocol.run_models import CapabilityHandoff
from sophia_forge_protocol.run_models import CapabilityAdded, CapabilityAdoption, CapabilityAdoptionReport


class _FakePylon:
    def __init__(self) -> None:
        self.refresh_calls = 0

    def refresh_tools(self) -> list[str]:
        self.refresh_calls += 1
        return ["get_market_ohlcv"]


def test_verify_capability_adoption_marks_visible_tools_as_adopted() -> None:
    agent = object.__new__(SophiaAgent)
    agent.pylon = _FakePylon()
    agent._get_tool_schemas = lambda: [
        ToolSchema(
            name="get_market_ohlcv",
            description="Get OHLCV market data.",
            input_schema={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        )
    ]

    report = agent._verify_capability_adoption(
        (
            CapabilityAdded(
                tool_name="get_market_ohlcv",
                service_name="scrivener",
                registration_path="services/sophia_pylon/src/pylon/core.py",
                when_to_use="Use when the user asks for historical OHLCV data.",
                input_schema={
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
                usage_example={"symbol": "ZN"},
            ),
        )
    )

    assert report.refreshed is True
    assert report.capabilities[0].adopted is True
    assert report.capabilities[0].handoff_ready is True
    assert report.capabilities[0].usage_example_valid is True
    assert report.capabilities[0].tool_name == "get_market_ohlcv"
    assert agent.pylon.refresh_calls == 1


def test_verify_capability_adoption_marks_incomplete_handoff() -> None:
    agent = object.__new__(SophiaAgent)
    agent.pylon = _FakePylon()
    agent._get_tool_schemas = lambda: [
        ToolSchema(
            name="get_market_ohlcv",
            description="Get OHLCV market data.",
            input_schema={
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        )
    ]

    report = agent._verify_capability_adoption(
        (
            CapabilityAdded(
                tool_name="get_market_ohlcv",
                service_name="scrivener",
                registration_path="services/sophia_pylon/src/pylon/core.py",
                when_to_use="Use when the user asks for historical OHLCV data.",
                input_schema={},
                usage_example={},
            ),
        )
    )

    assert report.capabilities[0].adopted is True
    assert report.capabilities[0].handoff_ready is False
    assert "input_schema missing" in report.capabilities[0].reason
    assert "usage_example missing" in report.capabilities[0].reason


def test_verify_capability_adoption_reports_refresh_failures() -> None:
    agent = object.__new__(SophiaAgent)

    class _FailingPylon:
        def refresh_tools(self) -> list[str]:
            raise RuntimeError("reload failed")

    agent.pylon = _FailingPylon()
    agent._get_tool_schemas = lambda: []

    report = agent._verify_capability_adoption(
        (
            CapabilityAdded(
                tool_name="get_market_ohlcv",
                service_name="scrivener",
                registration_path="services/sophia_pylon/src/pylon/core.py",
            ),
        )
    )

    assert report.refreshed is False
    assert report.capabilities[0].adopted is False
    assert "reload failed" in (report.error or "")


def test_remember_capability_handoffs_keeps_only_ready_tools() -> None:
    context = ConversationContext(session_id="session-1")
    capabilities = (
        CapabilityAdded(
            tool_name="get_market_ohlcv",
            service_name="scrivener",
            registration_path="services/sophia_pylon/src/pylon/core.py",
            when_to_use="Use when the user asks for historical OHLCV data.",
            usage_example={"symbol": "ZN"},
        ),
        CapabilityAdded(
            tool_name="search_research",
            service_name="tholos",
            registration_path="services/sophia_pylon/src/pylon/core.py",
            when_to_use="Use for research search.",
            usage_example={"query": "inflation"},
        ),
    )
    report = CapabilityAdoptionReport(
        refreshed=True,
        capabilities=(
            CapabilityAdoption(
                tool_name="get_market_ohlcv",
                service_name="scrivener",
                adopted=True,
                handoff_ready=True,
                usage_example_valid=True,
                schema_matches=True,
                resolved_input_schema={
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            ),
            CapabilityAdoption(
                tool_name="search_research",
                service_name="tholos",
                adopted=True,
                handoff_ready=False,
                usage_example_valid=False,
                schema_matches=False,
                resolved_input_schema={},
                reason="usage_example missing",
            ),
        ),
    )

    SophiaAgent._remember_capability_handoffs(context, capabilities, report)

    stored = context.metadata["tool_handoffs"]
    assert "get_market_ohlcv" in stored
    assert "search_research" not in stored
    assert stored["get_market_ohlcv"]["usage_example"] == {"symbol": "ZN"}


def test_build_system_prompt_includes_tool_handoff_guidance() -> None:
    agent = object.__new__(SophiaAgent)
    agent.preflight_result = None
    agent.canvas_id = None
    agent.profile = AgentProfile(agent_id="sophia", label="Sophia")
    agent.personality = Personality(raw_content="# Sophia")
    agent.soul = None
    agent.runtime_component_inventory = []

    context = ConversationContext(
        session_id="session-1",
        metadata={
            "tool_handoffs": {
                "get_market_ohlcv": {
                    "tool_name": "get_market_ohlcv",
                    "service_name": "scrivener",
                    "registration_path": "services/sophia_pylon/src/pylon/core.py",
                    "description": "Get OHLCV market data.",
                    "when_to_use": "Use when the user asks for historical OHLCV data.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"symbol": {"type": "string"}},
                        "required": ["symbol"],
                    },
                    "usage_example": {"symbol": "ZN"},
                }
            }
        },
    )

    prompt = agent._build_system_prompt(
        context=context,
        active_tools=[
            ToolSchema(
                name="get_market_ohlcv",
                description="Get OHLCV market data.",
                input_schema={
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            )
        ],
    )

    assert "Tool handoff guidance" in prompt
    assert "get_market_ohlcv" in prompt


def test_build_system_prompt_includes_forecast_source_policy() -> None:
    agent = object.__new__(SophiaAgent)
    agent.preflight_result = None
    agent.canvas_id = None
    agent.profile = AgentProfile(agent_id="sophia", label="Sophia")
    agent.personality = Personality(raw_content="# Sophia")
    agent.soul = None
    agent.runtime_component_inventory = []

    prompt = agent._build_system_prompt(
        active_tools=[
            ToolSchema(
                name="get_forecasts",
                description="Research forecasts.",
                input_schema={"type": "object", "properties": {}},
            ),
            ToolSchema(
                name="get_published_projection",
                description="Engine forecast.",
                input_schema={"type": "object", "properties": {}},
            ),
        ],
    )

    assert "Forecast source policy" in prompt
    assert "Use get_forecasts for external bank/research/street/house-view forecasts." in prompt
    assert "Use get_published_projection for our engine's production-approved forecast." in prompt


def test_build_system_prompt_includes_preference_persistence_policy() -> None:
    agent = object.__new__(SophiaAgent)
    agent.preflight_result = None
    agent.canvas_id = None
    agent.profile = AgentProfile(agent_id="sophia", label="Sophia")
    agent.personality = Personality(raw_content="# Sophia")
    agent.soul = None
    agent.runtime_component_inventory = []

    prompt = agent._build_system_prompt(
        active_tools=[
            ToolSchema(
                name="remember",
                description="Persist a durable preference.",
                input_schema={"type": "object", "properties": {}},
            ),
        ],
    )

    assert "Preference persistence policy" in prompt
    assert "Do not volunteer that you tried to save it to memory." in prompt
    assert "If any memory or persistence step fails internally, do not surface that failure" in prompt


def test_hydrate_capability_handoffs_merges_durable_registry(monkeypatch) -> None:
    agent = object.__new__(SophiaAgent)
    agent.settings = object()
    agent.read_policy = object()
    agent.write_policy = object()
    context = ConversationContext(session_id="session-1")

    class FakeForgeClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def load_capability_handoffs(self):
            return (
                CapabilityHandoff(
                    tool_name="get_market_ohlcv",
                    service_name="scrivener",
                    registration_path="services/sophia_pylon/src/pylon/core.py",
                    when_to_use="Use for OHLCV requests.",
                    usage_example={"symbol": "ZN"},
                ),
            )

    monkeypatch.setattr("sophia.agent.ForgeClient", FakeForgeClient)

    import asyncio

    asyncio.run(agent._hydrate_capability_handoffs(context))

    assert context.metadata["tool_handoffs"]["get_market_ohlcv"]["usage_example"] == {"symbol": "ZN"}
