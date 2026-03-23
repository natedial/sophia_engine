from sophia.llm.types import Message, Role
from sophia.memory import MemoryManager, MemoryManagerConfig
from sophia.memory.store import score_records
from sophia.memory.types import MemoryLevel, MemoryRecord, MemorySnapshot, utc_now


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


def test_user_endorsed_resources_become_global_semantic_memory() -> None:
    manager = MemoryManager(config=MemoryManagerConfig())
    manager.ingest_turn(
        session_id="session-a",
        user_message=(
            "Can you search for a good breakdown of the FOMC's current makeup of hawks "
            "versus doves? And anything I should keep in mind heading into the FOMC meeting?\n\n"
            "Couple good resources for this:\n"
            "https://itc-m.co/FedPrev\n"
            "https://itc-m.com/HawkDove"
        ),
        assistant_message="I will use them.",
    )

    snapshot = manager.recall(
        session_id="session-b",
        query="hawk dove FOMC breakdown",
        messages=[],
    )

    resource_records = [
        rec for rec in snapshot.semantic if rec.metadata.get("source") == "user_endorsed_resource"
    ]
    urls = {rec.metadata.get("url") for rec in resource_records}

    assert "https://itc-m.co/FedPrev" in urls
    assert "https://itc-m.com/HawkDove" in urls
    assert all(rec.session_id is None for rec in resource_records)
    assert any("FOMC" in rec.content for rec in resource_records)


def test_plain_url_without_endorsement_is_not_stored_as_resource_memory() -> None:
    manager = MemoryManager(config=MemoryManagerConfig())
    manager.ingest_turn(
        session_id="session-a",
        user_message="Can you access this link? https://example.com/report",
        assistant_message="I cannot access it here.",
    )

    semantic_records = manager.store.list_records(
        session_id=None,
        levels={MemoryLevel.SEMANTIC},
        limit=None,
        newest_first=True,
    )

    assert not any(rec.metadata.get("source") == "user_endorsed_resource" for rec in semantic_records)


def test_resource_recall_has_dedicated_budget() -> None:
    manager = MemoryManager(
        config=MemoryManagerConfig(
            semantic_recall_k=1,
            resource_recall_k=1,
        )
    )
    manager.ingest_turn(
        session_id="session-a",
        user_message=(
            "Find a FOMC hawk dove breakdown.\n\n"
            "Good resources for this:\n"
            "https://itc-m.com/HawkDove"
        ),
        assistant_message="Noted.",
    )
    manager.ingest_turn(
        session_id="session-a",
        user_message="We decided to focus on inflation and labor-market crosscurrents.",
        assistant_message="Understood.",
    )

    snapshot = manager.recall(
        session_id="session-a",
        query="FOMC hawk dove inflation crosscurrents",
        messages=[],
    )

    assert any(rec.metadata.get("source") == "user_endorsed_resource" for rec in snapshot.semantic)
    assert any(rec.metadata.get("source") != "user_endorsed_resource" for rec in snapshot.semantic)


def test_prompt_render_separates_resource_memory_from_semantic_memory() -> None:
    snapshot = MemorySnapshot(
        lessons=[],
        working_lines=[],
        episodic=[],
        semantic=[
            MemoryRecord(
                level=MemoryLevel.SEMANTIC,
                session_id=None,
                content="User-endorsed resource for FOMC makeup: https://itc-m.co/FedPrev.",
                tags={"resource", "user_endorsed_source", "link"},
                metadata={
                    "source": "user_endorsed_resource",
                    "url": "https://itc-m.co/FedPrev",
                },
            ),
            MemoryRecord(
                level=MemoryLevel.SEMANTIC,
                session_id="session-a",
                content="User preference: concise answers.",
                tags={"preference"},
            ),
        ],
    )

    text = snapshot.to_prompt_text()

    assert "treat those links as user-endorsed starting points" in text
    assert "Resource memory:" in text
    assert "- User-endorsed resource for FOMC makeup: https://itc-m.co/FedPrev." in text
    assert "Semantic memory:" in text
    assert "- User preference: concise answers." in text


def test_prompt_trimming_drops_general_semantic_before_resource_memory() -> None:
    snapshot = MemorySnapshot(
        lessons=[],
        working_lines=[],
        episodic=[],
        semantic=[
            MemoryRecord(
                level=MemoryLevel.SEMANTIC,
                session_id=None,
                content=(
                    "User-endorsed resource for FOMC hawk dove breakdown: "
                    "https://itc-m.com/HawkDove."
                ),
                tags={"resource", "user_endorsed_source", "link"},
                metadata={
                    "source": "user_endorsed_resource",
                    "url": "https://itc-m.com/HawkDove",
                },
                salience=0.88,
            ),
            MemoryRecord(
                level=MemoryLevel.SEMANTIC,
                session_id="session-a",
                content=(
                    "Project decision: capture a verbose semantic note that should be "
                    "trimmed before the endorsed resource when prompt budget is tight."
                ),
                tags={"decision"},
                salience=0.6,
            ),
        ],
    )

    text = snapshot.to_prompt_text(max_chars=220)

    assert "Resource memory:" in text
    assert "https://itc-m.com/HawkDove" in text
    assert "Project decision:" not in text


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
