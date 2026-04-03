from __future__ import annotations

import json
from pathlib import Path

import pytest

from sophia.agent import AgentConfig, SophiaAgent
from sophia.config import Settings
from sophia.context import ConversationContext
from sophia.events import EventType
from sophia.llm.types import (
    CompletionResponse,
    Message,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolSchema,
)
from sophia.memory import MemoryManager, MemoryManagerConfig
from sophia.memory.store import InMemoryMemoryStore


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

    async def stream(self, **kwargs):  # pragma: no cover - stream disabled in test
        raise AssertionError("stream() should not be called in this test")

    async def close(self) -> None:
        return None


class DummyPylon:
    def get_tools(self, only_healthy: bool = True):
        return []

    async def execute_tool(self, name: str, payload: dict):
        raise AssertionError("No tool execution expected in this test")


class DummyToolResult:
    def __init__(self, *, success: bool = True, payload: dict | None = None) -> None:
        self.success = success
        self._payload = payload or {
            "results": [
                {
                    "chunk_id": "c-1",
                    "source_path": "test.pdf",
                    "page_number": 1,
                    "text": "evidence",
                }
            ]
        }

    def to_content(self) -> str:
        return json.dumps(self._payload)


class DummyToolDef:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"Tool {name}"

    def to_generic_schema(self) -> dict:
        return {"input_schema": {"type": "object", "properties": {}}}


class DummyPylonWithTools(DummyPylon):
    def __init__(
        self,
        tool_names: list[str],
        *,
        tool_result: DummyToolResult | None = None,
    ) -> None:
        self._tools = [DummyToolDef(name) for name in tool_names]
        self.executions: list[tuple[str, dict]] = []
        self._tool_result = tool_result or DummyToolResult()

    def get_tools(self, only_healthy: bool = True):
        return self._tools

    async def execute_tool(self, name: str, payload: dict):
        self.executions.append((name, payload))
        return self._tool_result


class SequencedPylonWithTools(DummyPylon):
    def __init__(
        self,
        tool_names: list[str],
        *,
        tool_results: list[DummyToolResult],
    ) -> None:
        self._tools = [DummyToolDef(name) for name in tool_names]
        self.executions: list[tuple[str, dict]] = []
        self._tool_results = list(tool_results)

    def get_tools(self, only_healthy: bool = True):
        return self._tools

    async def execute_tool(self, name: str, payload: dict):
        self.executions.append((name, payload))
        if self._tool_results:
            return self._tool_results.pop(0)
        return DummyToolResult(payload={"results": [], "count": 0, "query": payload.get("query", "")})


class ToolRecordingProvider(DummyProvider):
    def __init__(self) -> None:
        super().__init__()
        self.tools_seen: list[list[str]] = []

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
        self.tools_seen.append([t.name for t in (tools or [])])
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content="ok"),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


class ToolLoopProvider(DummyProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.saw_tools_disabled = False

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
        self.calls += 1
        if tools:
            return CompletionResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(
                            id=f"call-{self.calls}",
                            name="search_series",
                            input={"query": "health care wages"},
                        )
                    ],
                ),
                stop_reason=StopReason.TOOL_USE,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )

        self.saw_tools_disabled = True
        return CompletionResponse(
            message=Message(
                role=Role.ASSISTANT,
                content="I could not find a sector-specific match in the fetched tool results.",
            ),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


class CitationProvider(DummyProvider):
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
            message=Message(
                role=Role.ASSISTANT,
                content="Claim (source_path: test.pdf, p.1, chunk_id: c-1)",
            ),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


class WebPreferenceProvider(DummyProvider):
    def __init__(self) -> None:
        super().__init__()
        self.tools_seen: list[list[str]] = []

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
        tool_names = [t.name for t in (tools or [])]
        self.tools_seen.append(tool_names)
        if "search_web" in tool_names:
            return CompletionResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call-web",
                            name="search_web",
                            input={"query": "nfp forecasts"},
                        )
                    ],
                ),
                stop_reason=StopReason.TOOL_USE,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )
        return CompletionResponse(
            message=Message(
                role=Role.ASSISTANT,
                content="Claim (source_path: test.pdf, p.1, chunk_id: c-1)",
            ),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


class LiveWebFallbackProvider(DummyProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.tools_seen: list[list[str]] = []

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
        self.calls += 1
        tool_names = [t.name for t in (tools or [])]
        self.tools_seen.append(tool_names)
        if self.calls == 1 and "search_web" in tool_names:
            return CompletionResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call-live-web",
                            name="search_web",
                            input={"query": "Lorie Logan speech today"},
                        )
                    ],
                ),
                stop_reason=StopReason.TOOL_USE,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )
        return CompletionResponse(
            message=Message(
                role=Role.ASSISTANT,
                content="Bottom line: today's Logan remarks were retrieved from web sources.",
            ),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )


@pytest.mark.asyncio
async def test_agent_emits_skill_activation_and_injects_skill_context(tmp_path: Path) -> None:
    personality_file = tmp_path / "config" / "personality.md"
    personality_file.parent.mkdir(parents=True)
    personality_file.write_text("# Sophia\n\n## Style\nPlain.", encoding="utf-8")

    soul_file = tmp_path / "config" / "soul.md"
    soul_file.write_text("Soul text", encoding="utf-8")

    skill_file = tmp_path / "skills" / "release-calendar-query-formatting" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\n"
        "name: release-calendar-query-formatting\n"
        "description: economic release schedule this week upcoming dates\n"
        "---\n\n"
        "Use deterministic release formatting.",
        encoding="utf-8",
    )

    settings = Settings(
        personality_path=personality_file,
        soul_path=soul_file,
        lessons_path=tmp_path / "config" / "LESSONS.md",
        skills_enabled=True,
        skills_path=tmp_path / "skills",
        skills_max_loaded_chars=4000,
        skills_implicit_match_min_overlap=2,
        openai_api_key="test-key",
        llm_model="test-model",
        agent_fs_read_allowlist=f"{tmp_path / 'config'},{tmp_path / 'skills'},.sophia",
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
    context = ConversationContext(session_id="test-session")

    events = [event async for event in agent.run("show this week release schedule", context)]

    skill_events = [event for event in events if event.type == EventType.SKILL_ACTIVATED]
    assert len(skill_events) == 1
    assert skill_events[0].data["name"] == "release-calendar-query-formatting"

    assert provider.system_prompts
    assert "Active skill" in provider.system_prompts[0]
    assert "release-calendar-query-formatting" in provider.system_prompts[0]


def test_agent_rejects_memory_path_outside_write_allowlist(tmp_path: Path) -> None:
    personality_file = tmp_path / "config" / "personality.md"
    personality_file.parent.mkdir(parents=True)
    personality_file.write_text("# Sophia", encoding="utf-8")

    soul_file = tmp_path / "config" / "soul.md"
    soul_file.write_text("Soul", encoding="utf-8")

    settings = Settings(
        personality_path=personality_file,
        soul_path=soul_file,
        skills_enabled=False,
        openai_api_key="test-key",
        llm_model="test-model",
        memory_store_backend="sqlite",
        memory_store_path=tmp_path / "memory.db",
        agent_fs_enforce_write_policy=True,
        agent_fs_write_allowlist=".sophia",
        agent_fs_enforce_read_policy=False,
    )

    with pytest.raises(PermissionError):
        SophiaAgent(
            provider=DummyProvider(),
            settings=settings,
            pylon=DummyPylon(),
            preflight_result=None,
            agent_config=AgentConfig(stream=False),
        )


def test_agent_rejects_personality_path_outside_read_allowlist(tmp_path: Path) -> None:
    personality_file = tmp_path / "config" / "personality.md"
    personality_file.parent.mkdir(parents=True)
    personality_file.write_text("# Sophia", encoding="utf-8")

    soul_file = tmp_path / "config" / "soul.md"
    soul_file.write_text("Soul", encoding="utf-8")

    settings = Settings(
        personality_path=personality_file,
        soul_path=soul_file,
        skills_enabled=False,
        openai_api_key="test-key",
        llm_model="test-model",
        memory_store_backend="memory",
        agent_fs_enforce_read_policy=True,
        agent_fs_read_allowlist=".sophia",
    )

    with pytest.raises(PermissionError):
        SophiaAgent(
            provider=DummyProvider(),
            settings=settings,
            pylon=DummyPylon(),
            preflight_result=None,
            agent_config=AgentConfig(stream=False),
        )


@pytest.mark.asyncio
async def test_agent_scopes_tools_by_skill_allowlist(tmp_path: Path) -> None:
    personality_file = tmp_path / "config" / "personality.md"
    personality_file.parent.mkdir(parents=True)
    personality_file.write_text("# Sophia\n\n## Style\nPlain.", encoding="utf-8")

    soul_file = tmp_path / "config" / "soul.md"
    soul_file.write_text("Soul text", encoding="utf-8")

    skill_file = tmp_path / "skills" / "release-calendar-query-formatting" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\n"
        "name: release-calendar-query-formatting\n"
        "description: economic release schedule this week upcoming dates\n"
        "tool_allowlist: get_releases_week\n"
        "---\n\n"
        "Use deterministic release formatting.",
        encoding="utf-8",
    )

    settings = Settings(
        personality_path=personality_file,
        soul_path=soul_file,
        lessons_path=tmp_path / "config" / "LESSONS.md",
        skills_enabled=True,
        skills_path=tmp_path / "skills",
        skills_max_loaded_chars=4000,
        skills_implicit_match_min_overlap=2,
        openai_api_key="test-key",
        llm_model="test-model",
        memory_store_backend="memory",
        agent_fs_read_allowlist=f"{tmp_path / 'config'},{tmp_path / 'skills'},.sophia",
    )
    provider = ToolRecordingProvider()
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=DummyPylonWithTools(["get_releases_week", "get_releases_upcoming"]),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
        memory_manager=MemoryManager(
            store=InMemoryMemoryStore(),
            config=MemoryManagerConfig(enabled=False),
        ),
    )
    context = ConversationContext(session_id="test-session-tools")

    _ = [event async for event in agent.run("show this week release schedule", context)]

    assert provider.tools_seen
    assert provider.tools_seen[0] == ["get_releases_week"]


@pytest.mark.asyncio
async def test_agent_injects_seed_lessons_into_memory_context(tmp_path: Path) -> None:
    personality_file = tmp_path / "config" / "personality.md"
    personality_file.parent.mkdir(parents=True)
    personality_file.write_text("# Sophia\n\n## Style\nPlain.", encoding="utf-8")

    soul_file = tmp_path / "config" / "soul.md"
    soul_file.write_text("Soul text", encoding="utf-8")

    lessons_file = tmp_path / "config" / "LESSONS.md"
    lessons_file.write_text(
        "# Lessons\n\n- Always verify release dates using tools.\n",
        encoding="utf-8",
    )

    settings = Settings(
        personality_path=personality_file,
        soul_path=soul_file,
        lessons_path=lessons_file,
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
    )
    context = ConversationContext(session_id="test-session-lessons")

    _ = [event async for event in agent.run("check this week's releases", context)]

    assert provider.system_prompts
    assert "Lessons memory:" in provider.system_prompts[0]
    assert "Always verify release dates using tools." in provider.system_prompts[0]


@pytest.mark.asyncio
async def test_agent_injects_resource_memory_guidance_into_system_prompt(tmp_path: Path) -> None:
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
        memory_resource_top_k=1,
        memory_semantic_top_k=1,
        agent_fs_read_allowlist=f"{tmp_path / 'config'},.sophia",
    )
    provider = DummyProvider()
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=DummyPylon(),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    agent.memory.ingest_turn(
        session_id="test-session-resources",
        user_message=(
            "Find a FOMC hawk dove breakdown.\n\n"
            "Helpful resources for this:\n"
            "https://itc-m.com/HawkDove"
        ),
        assistant_message="Noted.",
    )
    context = ConversationContext(session_id="test-session-resources")

    _ = [event async for event in agent.run("what should I read for FOMC hawk dove context", context)]

    assert provider.system_prompts
    assert "Resource memory:" in provider.system_prompts[0]
    assert "user-endorsed starting points for sourcing" in provider.system_prompts[0]
    assert "https://itc-m.com/HawkDove" in provider.system_prompts[0]


@pytest.mark.asyncio
async def test_agent_injects_research_retrieval_policy_when_tholos_tools_present(
    tmp_path: Path,
) -> None:
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
        pylon=DummyPylonWithTools(["search_research", "get_research_chunk"]),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="test-session-research-protocol")

    _ = [event async for event in agent.run("summarize tariff debate evidence", context)]

    assert provider.system_prompts
    assert "Research retrieval policy" in provider.system_prompts[0]
    assert "keyword_weight=0.65" in provider.system_prompts[0]
    assert "chunk_id" in provider.system_prompts[0]


@pytest.mark.asyncio
async def test_agent_injects_readwise_policy_when_readwise_tools_present(
    tmp_path: Path,
) -> None:
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
        pylon=DummyPylonWithTools(
            ["readwise_list_commands", "readwise_run_command"]
        ),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="test-session-readwise-policy")

    _ = [event async for event in agent.run("search my readwise highlights for Powell notes", context)]

    assert provider.system_prompts
    assert "Readwise policy" in provider.system_prompts[0]
    assert "readwise_list_commands" in provider.system_prompts[0]
    assert "readwise_run_command" in provider.system_prompts[0]
    assert "reader-search-documents" in provider.system_prompts[0]


def test_should_enforce_tools_for_research_queries() -> None:
    tools = [
        ToolSchema(
            name="search_research",
            description="",
            input_schema={"type": "object", "properties": {}},
        )
    ]

    assert SophiaAgent._should_enforce_tools(
        "What's the broad range of views on tariffs?",
        tools,
    )
    assert SophiaAgent._should_enforce_tools(
        "Why does BofA see refund payments as likely in chunk_id c-17?",
        tools,
    )
    assert SophiaAgent._should_enforce_tools(
        "any specific citations on section 122",
        tools,
    )
    assert SophiaAgent._should_enforce_tools(
        "what documents is that take from?",
        tools,
    )
    assert not SophiaAgent._should_enforce_tools("Tell me a short joke.", tools)


def test_requires_explicit_citations_and_structured_format() -> None:
    assert SophiaAgent._requires_explicit_citations("any specific citations on section 122")
    assert SophiaAgent._requires_explicit_citations("what documents is that take from?")
    assert not SophiaAgent._requires_explicit_citations("give me a short joke")

    assert SophiaAgent._has_structured_citations(
        "Claim (source_path: a.pdf, p.6, chunk_id: c-1)"
    )
    assert not SophiaAgent._has_structured_citations("Claim (supabase:214, p.6)")


def test_requires_research_citations_for_synthesis_and_legal_recency_queries() -> None:
    tools = [
        ToolSchema(
            name="search_research",
            description="",
            input_schema={"type": "object", "properties": {}},
        )
    ]

    assert SophiaAgent._requires_research_citations(
        "What's the broad range of views on tariffs being struck down by the supreme court last week?",
        tools,
    )
    assert SophiaAgent._requires_research_citations(
        "any specific citations on section 122",
        tools,
    )
    assert SophiaAgent._requires_research_citations(
        "What's the range of NFP forecasts for this upcoming Friday?",
        tools,
    )
    assert not SophiaAgent._requires_research_citations(
        "What's the latest CPI print?",
        tools,
    )


def test_should_prioritize_local_research_for_forecast_style_queries() -> None:
    tools = [
        ToolSchema(
            name="search_research",
            description="",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolSchema(
            name="search_web",
            description="",
            input_schema={"type": "object", "properties": {}},
        ),
    ]

    assert SophiaAgent._should_prioritize_local_research(
        "What's the range of NFP forecasts for this upcoming Friday?",
        tools,
    )
    assert not SophiaAgent._should_prioritize_local_research(
        "Search online for the latest Reuters NFP preview.",
        tools,
    )
    assert not SophiaAgent._should_prioritize_local_research(
        "What's our engine forecast for core CPI?",
        tools,
    )


def test_forecast_request_classifier_distinguishes_research_engine_and_compare() -> None:
    assert (
        SophiaAgent._classify_forecast_request(
            "What's the range of bank NFP forecasts for Friday?"
        )
        == "research"
    )
    assert (
        SophiaAgent._classify_forecast_request(
            "What's our engine forecast for CPI?"
        )
        == "engine"
    )
    assert (
        SophiaAgent._classify_forecast_request(
            "Compare our model forecast for CPI versus street forecasts."
        )
        == "compare"
    )


def test_engine_forecast_requests_do_not_require_research_citations() -> None:
    tools = [
        ToolSchema(
            name="search_research",
            description="",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolSchema(
            name="get_research_chunk",
            description="",
            input_schema={"type": "object", "properties": {}},
        ),
    ]

    assert not SophiaAgent._requires_research_citations(
        "Show me our published projection for macro_us_inflation.",
        tools,
    )


def test_build_research_prefetch_input_uses_tuned_defaults() -> None:
    payload = SophiaAgent._build_research_prefetch_input(
        "  any specific citations on   section 122  "
    )
    assert payload["query"] == "any specific citations on section 122"
    assert payload["limit"] == 8
    assert payload["keyword_weight"] == 0.65
    assert payload["semantic_weight"] == 0.35
    assert payload["min_lexical_score"] == 0.08
    assert payload["semantic_tail_mode"] == "demote"
    assert payload["max_per_source"] == 2

    recall_payload = SophiaAgent._build_research_prefetch_input(
        "tariffs and supreme court",
        query_override="tariff supreme court",
        recall_mode=True,
    )
    assert recall_payload["query"] == "tariff supreme court"
    assert recall_payload["min_lexical_score"] == 0.0
    assert recall_payload["semantic_tail_mode"] == "keep"
    assert recall_payload["max_per_source"] == 2


def test_build_research_probe_queries_normalizes_keywords() -> None:
    probes = SophiaAgent._build_research_probe_queries(
        "What's the broad range of views on tariffs being struck down by the supreme court last week?"
    )
    assert probes
    assert probes[0].startswith("What's the broad range")
    assert any("tariff" in probe for probe in probes)

    ieepa_probes = SophiaAgent._build_research_probe_queries(
        "what do reports since last friday expect about IEEPA tariffs being ruled unconstitutional adn fallout"
    )
    assert any("ieepa" in probe for probe in ieepa_probes)
    assert any("tariff" in probe for probe in ieepa_probes)
    assert "ieepa" in ieepa_probes[1]

    ruling_probes = SophiaAgent._build_research_probe_queries(
        "after the supreme court ruling on ieepa tariffs, what next?"
    )
    assert any("ieepa tariff supreme court ruling" in probe for probe in ruling_probes)


def test_search_result_count_parses_json_payload() -> None:
    assert SophiaAgent._search_result_count('{"count": 3, "results": []}') == 3
    assert SophiaAgent._search_result_count('{"results": [{"chunk_id":"c-1"}]}') == 1
    assert SophiaAgent._search_result_count("not-json") == 0


def test_build_evidence_fallback_response_only_for_report_style_prompts() -> None:
    rows = [
        {
            "chunk_id": "c-1",
            "source_path": "supabase:1",
            "page_number": 5,
            "text": "Analysts expect a limited near-term market impact if IEEPA tariffs are struck down.",
        }
    ]
    assert (
        SophiaAgent._build_evidence_fallback_response(
            user_message="what do reports expect after the ruling?",
            evidence_rows=rows,
        )
        is not None
    )
    assert (
        SophiaAgent._build_evidence_fallback_response(
            user_message="any specific citations on section 122",
            evidence_rows=rows,
        )
        is None
    )


def test_chunk_id_extraction_from_tholos_tool_output() -> None:
    search_payload = (
        '{\n'
        '  "results": [\n'
        '    {"chunk_id": "c-1", "text": "a"},\n'
        '    {"chunk_id": "c-2", "text": "b"}\n'
        "  ]\n"
        "}"
    )
    chunk_payload = '{"chunk_id":"c-3","text":"full chunk"}'

    assert SophiaAgent._extract_chunk_ids_from_tool_output("search_research", search_payload) == {
        "c-1",
        "c-2",
    }
    assert SophiaAgent._extract_chunk_ids_from_tool_output("get_research_chunk", chunk_payload) == {
        "c-3"
    }


def test_invalid_chunk_citations_are_detected() -> None:
    text = (
        "Evidence A (source_path: a.pdf, p.1, chunk_id: c-1)\n"
        "Evidence B (source_path: b.pdf, p.2, chunk_id: fake-999)"
    )
    assert SophiaAgent._has_invalid_chunk_citations(
        text,
        allowed_chunk_ids={"c-1", "c-2"},
    )
    assert not SophiaAgent._has_invalid_chunk_citations(
        "No citations here.",
        allowed_chunk_ids={"c-1", "c-2"},
    )
    assert SophiaAgent._has_invalid_chunk_citations(
        "Claim (chunk_id: c-1)",
        allowed_chunk_ids=set(),
    )
    assert SophiaAgent._has_invalid_chunk_citations(
        "Claim (chunk_id “c-1”)",
        allowed_chunk_ids=set(),
    )
    assert SophiaAgent._has_invalid_chunk_citations(
        "Claim (chunk_id: §4.2)",
        allowed_chunk_ids={"c-1"},
    )
    assert SophiaAgent._has_invalid_chunk_citations(
        "Claim (supabase:214, p.6)",
        allowed_chunk_ids={"c-1"},
    )
    assert SophiaAgent._has_invalid_chunk_citations(
        "Claim (source_path: paper.pdf, p.6)",
        allowed_chunk_ids={"c-1"},
    )
    assert not SophiaAgent._has_invalid_chunk_citations(
        "Claim (source_path: supabase:214, p.6, chunk_id: c-1)",
        allowed_chunk_ids={"c-1"},
    )


@pytest.mark.asyncio
async def test_agent_refuses_ungrounded_research_answer_when_tools_not_used(
    tmp_path: Path,
) -> None:
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
        pylon=DummyPylonWithTools(["search_research"]),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="test-session-grounding")

    final = await agent.chat(
        "Give me research-backed views on tariffs with sources.",
        context,
    )

    assert "couldn't produce citation-grounded output" in final.content
    assert len(provider.system_prompts) >= 2


@pytest.mark.asyncio
async def test_agent_refuses_uncited_research_synthesis_without_tool_grounding(
    tmp_path: Path,
) -> None:
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
        pylon=DummyPylonWithTools(["search_research"]),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="test-session-research-views")

    final = await agent.chat(
        "What's the broad range of views on tariffs being struck down by the supreme court last week?",
        context,
    )

    assert "couldn't produce citation-grounded output" in final.content


@pytest.mark.asyncio
async def test_agent_forces_final_synthesis_after_tool_only_loop(tmp_path: Path) -> None:
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
    provider = ToolLoopProvider()
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=DummyPylonWithTools(["search_series"]),
        preflight_result=None,
        agent_config=AgentConfig(stream=False, max_tool_iterations=2),
    )
    context = ConversationContext(session_id="test-session-tool-loop")

    final = await agent.chat(
        "Find a health care wage series and summarize it.",
        context,
    )

    assert provider.saw_tools_disabled is True
    assert "sector-specific match" in final.content


@pytest.mark.asyncio
async def test_agent_prefetches_research_before_completion_for_citation_turns(
    tmp_path: Path,
) -> None:
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
    provider = CitationProvider()
    pylon = DummyPylonWithTools(["search_research"])
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=pylon,
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="test-session-prefetch")

    final = await agent.chat(
        "any specific citations on section 122",
        context,
    )

    assert "chunk_id: c-1" in final.content
    assert pylon.executions
    tool_name, payload = pylon.executions[0]
    assert tool_name == "search_research"
    assert payload["query"] == "any specific citations on section 122"
    assert payload["keyword_weight"] == 0.65


@pytest.mark.asyncio
async def test_agent_prefetches_research_for_forecast_range_turns(
    tmp_path: Path,
) -> None:
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
    provider = CitationProvider()
    pylon = DummyPylonWithTools(["search_research"])
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=pylon,
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="test-session-forecast-prefetch")

    final = await agent.chat(
        "What's the range of NFP forecasts for this upcoming Friday?",
        context,
    )

    assert "chunk_id: c-1" in final.content
    assert pylon.executions
    tool_name, payload = pylon.executions[0]
    assert tool_name == "search_research"
    assert payload["query"] == "What's the range of NFP forecasts for this upcoming Friday?"
    assert payload["keyword_weight"] == 0.65


@pytest.mark.asyncio
async def test_agent_hides_web_tools_on_first_pass_when_local_research_hits(
    tmp_path: Path,
) -> None:
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
    provider = WebPreferenceProvider()
    pylon = DummyPylonWithTools(["search_research", "search_web", "get_web_context"])
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=pylon,
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="test-session-local-first")

    final = await agent.chat(
        "What's the range of NFP forecasts for this upcoming Friday?",
        context,
    )

    assert "chunk_id: c-1" in final.content
    assert pylon.executions
    assert pylon.executions[0][0] == "search_research"
    assert provider.tools_seen
    assert "search_web" not in provider.tools_seen[0]
    assert "get_web_context" not in provider.tools_seen[0]


@pytest.mark.asyncio
async def test_agent_requests_confirmation_before_web_when_local_research_prefetch_is_empty(
    tmp_path: Path,
) -> None:
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
    provider = WebPreferenceProvider()
    pylon = DummyPylonWithTools(
        ["search_research", "search_web", "get_web_context"],
        tool_result=DummyToolResult(payload={"results": [], "count": 0, "query": "nfp"}),
    )
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=pylon,
        preflight_result=None,
        agent_config=AgentConfig(stream=False, max_tool_iterations=1),
    )
    context = ConversationContext(session_id="test-session-web-fallback")

    final = await agent.chat(
        "What's the range of NFP forecasts for this upcoming Friday?",
        context,
    )

    assert pylon.executions
    assert pylon.executions[0][0] == "search_research"
    assert provider.tools_seen == []
    assert "I paused before using external sources" in final.content
    assert "couldn't find matching corpus hits in the current scope" in final.content
    assert "widen the corpus scope or switch to web" in final.content


@pytest.mark.asyncio
async def test_agent_switches_to_web_for_live_current_request_when_local_research_prefetch_is_empty(
    tmp_path: Path,
) -> None:
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
    provider = LiveWebFallbackProvider()
    pylon = SequencedPylonWithTools(
        ["search_research", "search_web", "get_web_context"],
        tool_results=[
            DummyToolResult(payload={"results": [], "count": 0, "query": "lorie logan speech today"}),
            DummyToolResult(
                payload={
                    "query": "Lorie Logan speech today",
                    "results": [
                        {
                            "title": "Speech",
                            "url": "https://example.com/logan",
                            "description": "Remarks by Lorie Logan.",
                        }
                    ],
                    "total_results": 1,
                }
            ),
        ],
    )
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=pylon,
        preflight_result=None,
        agent_config=AgentConfig(stream=False, max_tool_iterations=3),
    )
    context = ConversationContext(session_id="test-session-live-web-fallback")

    final = await agent.chat(
        "Please analyze today's Lorie Logan speech and let me know what the main takeaways are for bank asset purchases.",
        context,
    )

    assert [name for name, _ in pylon.executions[:2]] == ["search_research", "search_web"]
    assert provider.tools_seen
    assert "search_web" in provider.tools_seen[0]
    assert "I paused before using external sources" not in final.content
    assert "today's Logan remarks were retrieved from web sources" in final.content


@pytest.mark.asyncio
async def test_agent_emits_local_research_web_fallback_reason_when_prefetch_is_empty(
    tmp_path: Path,
) -> None:
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
    provider = WebPreferenceProvider()
    pylon = DummyPylonWithTools(
        ["search_research", "search_web", "get_web_context"],
        tool_result=DummyToolResult(payload={"results": [], "count": 0, "query": "nfp"}),
    )
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=pylon,
        preflight_result=None,
        agent_config=AgentConfig(stream=False, max_tool_iterations=1),
    )
    context = ConversationContext(session_id="test-session-web-fallback-event")

    events = [
        event
        async for event in agent.run(
            "What's the range of NFP forecasts for this upcoming Friday?",
            context,
        )
    ]

    fallback_events = [event for event in events if event.type == EventType.WORKFLOW_DECISION]
    assert fallback_events
    assert fallback_events[0].data["category"] == "local_research_web_fallback"
    assert fallback_events[0].data["reason"] == "local_research_prefetch_returned_no_hits"
    assert fallback_events[0].data["details"]["prefetch_attempts"] >= 1
    assert fallback_events[0].data["details"]["successful_prefetches"] == 0
    assert fallback_events[0].data["details"]["web_tools_enabled"] == [
        "get_web_context",
        "search_web",
    ]
    message_events = [event for event in events if event.type == EventType.MESSAGE_END]
    assert message_events
    assert "I paused before using external sources" in message_events[-1].data["message"].content


@pytest.mark.asyncio
async def test_agent_uses_evidence_fallback_for_report_queries(
    tmp_path: Path,
) -> None:
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
    pylon = DummyPylonWithTools(["search_research"])
    agent = SophiaAgent(
        provider=provider,
        settings=settings,
        pylon=pylon,
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
    )
    context = ConversationContext(session_id="test-session-report-fallback")

    final = await agent.chat(
        "now that the supreme court ruling on IEEPA is out, what do reports since last friday expect about tariff fallout?",
        context,
    )

    assert "Retrieved research evidence currently indicates" in final.content
    assert "(source_path: test.pdf, p.1, chunk_id: c-1)" in final.content
