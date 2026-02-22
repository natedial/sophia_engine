from sophia.llm.types import Message, Role
from sophia.memory import MemoryManager, MemoryManagerConfig
from sophia.memory.store import score_records
from sophia.memory.types import MemoryLevel, MemoryRecord, utc_now


def test_ingest_turn_extracts_semantic_facts() -> None:
    manager = MemoryManager(config=MemoryManagerConfig())
    manager.ingest_turn(
        session_id="session-a",
        user_message="My name is Nora. I prefer terse responses.",
        assistant_message="Understood.",
    )

    snapshot = manager.recall(
        session_id="session-a",
        query="what are my preferences",
        messages=[],
    )
    semantic_contents = [rec.content for rec in snapshot.semantic]

    assert any("User name is Nora." in content for content in semantic_contents)
    assert any("User preference:" in content for content in semantic_contents)


def test_working_memory_respects_window() -> None:
    manager = MemoryManager(
        config=MemoryManagerConfig(
            working_window=2,
            episodic_recall_k=0,
            semantic_recall_k=0,
        )
    )
    messages = [
        Message(role=Role.USER, content="one"),
        Message(role=Role.ASSISTANT, content="two"),
        Message(role=Role.USER, content="three"),
    ]

    snapshot = manager.recall(
        session_id="session-a",
        query="latest",
        messages=messages,
    )
    assert snapshot.working_lines == [
        "Assistant: two",
        "User: three",
    ]


def test_memory_is_session_scoped() -> None:
    manager = MemoryManager(config=MemoryManagerConfig())
    manager.ingest_turn(
        session_id="session-a",
        user_message="I prefer clear checklists.",
        assistant_message="Got it.",
    )

    snapshot = manager.recall(
        session_id="session-b",
        query="preferences",
        messages=[],
    )
    assert snapshot.semantic == []


def test_semantic_scoring_improves_paraphrase_matching() -> None:
    record = MemoryRecord(
        level=MemoryLevel.SEMANTIC,
        session_id="session-a",
        content="We should buy treasuries quickly when volatility drops.",
    )

    with_semantic = score_records(
        records=[record],
        session_id="session-a",
        query="purchase government bonds fast after volatility falls",
        limit=1,
        now=utc_now(),
        semantic_search_enabled=True,
        lexical_weight=0.45,
        semantic_weight=0.35,
    )[0].score
    without_semantic = score_records(
        records=[record],
        session_id="session-a",
        query="purchase government bonds fast after volatility falls",
        limit=1,
        now=utc_now(),
        semantic_search_enabled=False,
        lexical_weight=0.45,
        semantic_weight=0.35,
    )[0].score

    assert with_semantic > without_semantic
