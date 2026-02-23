from __future__ import annotations

from pathlib import Path

import pytest

from sophia.agent import AgentConfig, SophiaAgent
from sophia.config import Settings
from sophia.context import ConversationContext
from sophia.events import EventType
from sophia.llm.types import CompletionResponse, Message, Role, StopReason, TokenUsage
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


class DummyToolDef:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"Tool {name}"

    def to_generic_schema(self) -> dict:
        return {"input_schema": {"type": "object", "properties": {}}}


class DummyPylonWithTools(DummyPylon):
    def __init__(self, tool_names: list[str]) -> None:
        self._tools = [DummyToolDef(name) for name in tool_names]

    def get_tools(self, only_healthy: bool = True):
        return self._tools


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
