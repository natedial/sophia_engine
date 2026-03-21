from sophia.agent_local_tools import AgentLocalTools
from sophia.memory import MemoryManager, MemoryManagerConfig
from sophia.memory.store import InMemoryMemoryStore
from sophia.memory.types import MemoryLevel, MemoryRecord


def test_list_memory_includes_session_scoped_and_global_records() -> None:
    store = InMemoryMemoryStore()
    store.add(
        MemoryRecord(
            level=MemoryLevel.EPISODIC,
            session_id="session-a",
            content="User asked about inflation swaps.",
        )
    )
    store.add(
        MemoryRecord(
            level=MemoryLevel.LESSONS,
            session_id=None,
            content="Always verify release dates using tools.",
        )
    )
    tools = AgentLocalTools(
        MemoryManager(
            store=store,
            config=MemoryManagerConfig(),
        )
    )

    output = tools.list_memory(limit=10)

    assert "inflation swaps" in output
    assert "Always verify release dates using tools." in output


def test_list_memory_level_filter_includes_session_records() -> None:
    store = InMemoryMemoryStore()
    store.add(
        MemoryRecord(
            level=MemoryLevel.EPISODIC,
            session_id="session-a",
            content="User asked for a release calendar.",
        )
    )
    tools = AgentLocalTools(
        MemoryManager(
            store=store,
            config=MemoryManagerConfig(),
        )
    )

    output = tools.list_memory(level="episodic", limit=10)

    assert "release calendar" in output
