from __future__ import annotations

from pathlib import Path

import pytest

from sophia.agent import AgentConfig, SophiaAgent
from sophia.config import Settings
from sophia.context import ConversationContext
from sophia.history import (
    HistoryEventRecord,
    HistoryEventType,
    LosslessHistoryManager,
    SQLiteHistoryStore,
)
from sophia.llm.types import (
    CompletionResponse,
    Message,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
)
from sophia.memory import MemoryManager, MemoryManagerConfig
from sophia.memory.store import InMemoryMemoryStore


class HistoryToolResult:
    def __init__(self, *, success: bool = True, content: str = '{"ok":true}') -> None:
        self.success = success
        self._content = content

    def to_content(self) -> str:
        return self._content


class HistoryProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools=None,
        max_tokens: int = 4096,
    ) -> CompletionResponse:
        self.calls += 1
        if self.calls == 1:
            return CompletionResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tool-1",
                            name="search_series",
                            input={"query": "initial claims"},
                        )
                    ],
                ),
                stop_reason=StopReason.TOOL_USE,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )
        return CompletionResponse(
            message=Message(role=Role.ASSISTANT, content="Initial claims moved lower."),
            stop_reason=StopReason.END_TURN,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )

    async def stream(self, **kwargs):  # pragma: no cover - stream disabled in tests
        raise AssertionError("stream() should not be called in this test")

    async def close(self) -> None:
        return None


class HistoryToolDef:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name

    def to_generic_schema(self) -> dict:
        return {"input_schema": {"type": "object", "properties": {}}}


class HistoryPylon:
    def get_tools(self, only_healthy: bool = True):
        return [HistoryToolDef("search_series")]

    async def execute_tool(self, name: str, payload: dict):
        assert name == "search_series"
        assert "claims" in str(payload.get("query") or "").lower()
        return HistoryToolResult(content='{"series_id":"ICSA","title":"Initial Claims"}')


def test_lossless_history_store_persists_and_truncates_tool_results(tmp_path: Path) -> None:
    manager = LosslessHistoryManager.from_sqlite(
        db_path=tmp_path / "history.db",
        tool_result_max_chars=5,
    )

    manager.record_turn_input(
        session_id="session-a",
        run_id="run-1",
        parent_run_id=None,
        task_id=None,
        turn=1,
        user_message="Build a debug trace.",
    )
    manager.record_tool_end(
        session_id="session-a",
        run_id="run-1",
        parent_run_id=None,
        task_id=None,
        turn=1,
        tool_call=ToolCall(id="tool-1", name="search_series", input={"query": "claims"}),
        result="abcdefghijklmnopqrstuvwxyz",
        is_error=False,
    )

    records = manager.list_session_events(session_id="session-a", run_id="run-1")

    assert [record.event_type for record in records] == [
        HistoryEventType.TURN_INPUT,
        HistoryEventType.TOOL_END,
    ]
    assert records[1].payload["result"] == "abcde"
    assert records[1].payload["result_truncated"] is True
    assert records[1].payload["original_result_chars"] == 26


def test_search_sessions_applies_exclusions_before_hit_limit(tmp_path: Path) -> None:
    store = SQLiteHistoryStore(tmp_path / "history.db")

    for idx in range(5):
        store.append(
            HistoryEventRecord(
                session_id="exclude-me",
                event_type=HistoryEventType.TURN_INPUT,
                payload={"user_message": f"inflation outlook repeated {idx}"},
            )
        )

    store.append(
        HistoryEventRecord(
            session_id="keep-me",
            event_type=HistoryEventType.TURN_INPUT,
            payload={"user_message": "inflation outlook alternative session"},
        )
    )

    results = store.search_sessions(
        query="inflation outlook",
        exclude_session_ids={"exclude-me"},
        max_sessions=3,
        max_hits=5,
        max_results_per_session=5,
    )

    assert len(results) == 1
    assert results[0].session_id == "keep-me"


@pytest.mark.asyncio
async def test_agent_records_lossless_history_for_tool_turn(tmp_path: Path) -> None:
    personality_file = tmp_path / "config" / "personality.md"
    personality_file.parent.mkdir(parents=True)
    personality_file.write_text("# Sophia\n\n## Style\nPlain.", encoding="utf-8")

    soul_file = tmp_path / "config" / "soul.md"
    soul_file.write_text("Soul", encoding="utf-8")

    history_path = tmp_path / ".sophia" / "history.db"
    settings = Settings(
        personality_path=personality_file,
        soul_path=soul_file,
        lessons_path=tmp_path / "config" / "LESSONS.md",
        skills_enabled=False,
        openai_api_key="test-key",
        llm_model="test-model",
        history_enabled=True,
        history_store_path=history_path,
        agent_fs_read_allowlist=f"{tmp_path / 'config'},{tmp_path}",
        agent_fs_write_allowlist=str(tmp_path),
    )
    agent = SophiaAgent(
        provider=HistoryProvider(),
        settings=settings,
        pylon=HistoryPylon(),
        preflight_result=None,
        agent_config=AgentConfig(stream=False),
        memory_manager=MemoryManager(
            store=InMemoryMemoryStore(),
            config=MemoryManagerConfig(enabled=False),
        ),
    )
    context = ConversationContext(session_id="history-session")

    await agent.chat("Can you check initial claims?", context)

    store = SQLiteHistoryStore(history_path)
    records = store.list_events(session_id="history-session", limit=20)

    assert [record.event_type for record in records] == [
        HistoryEventType.TURN_INPUT,
        HistoryEventType.TOOL_START,
        HistoryEventType.TOOL_END,
        HistoryEventType.TURN_OUTPUT,
    ]
    assert records[0].payload["user_message"] == "Can you check initial claims?"
    assert records[1].payload["tool_call"]["name"] == "search_series"
    assert "ICSA" in records[2].payload["result"]
    assert records[3].payload["assistant_message"] == "Initial claims moved lower."
