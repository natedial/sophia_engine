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


def test_seed_lessons_are_included_in_memory_snapshot() -> None:
    manager = MemoryManager(
        config=MemoryManagerConfig(lessons_recall_k=3),
        seed_lessons=[
            "Always verify release dates using tools.",
            "Use exact calendar dates in answers.",
        ],
    )

    snapshot = manager.recall(
        session_id="session-a",
        query="release schedule",
        messages=[],
    )

    lesson_texts = [rec.content for rec in snapshot.lessons]
    assert any("Always verify release dates using tools." in text for text in lesson_texts)
    assert any("Use exact calendar dates in answers." in text for text in lesson_texts)


def test_explicit_directive_promotes_lesson_immediately() -> None:
    manager = MemoryManager(config=MemoryManagerConfig(lesson_promotion_min_repeats=3))
    manager.ingest_turn(
        session_id="session-a",
        user_message="From now on, always use YYYY-MM-DD dates.",
        assistant_message="Understood.",
    )

    snapshot = manager.recall(
        session_id="session-a",
        query="date format",
        messages=[],
    )
    lesson_texts = [rec.content for rec in snapshot.lessons]

    assert any("always use YYYY-MM-DD dates" in text for text in lesson_texts)


def test_repeated_preference_promotes_lesson_after_threshold() -> None:
    manager = MemoryManager(
        config=MemoryManagerConfig(
            lesson_promotion_min_repeats=2,
            lessons_recall_k=5,
        )
    )
    manager.ingest_turn(
        session_id="session-a",
        user_message="I prefer concise bullet answers.",
        assistant_message="Noted.",
    )
    first = manager.recall(session_id="session-a", query="style", messages=[])
    assert not any("concise bullet answers" in rec.content for rec in first.lessons)

    manager.ingest_turn(
        session_id="session-a",
        user_message="I prefer concise bullet answers.",
        assistant_message="Got it.",
    )
    second = manager.recall(session_id="session-a", query="style", messages=[])

    assert any("concise bullet answers" in rec.content for rec in second.lessons)
