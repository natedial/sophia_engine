from pathlib import Path

from sophia.memory import MemoryLevel, MemoryManager, MemoryManagerConfig, SQLiteMemoryStore


def test_sqlite_store_persists_between_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"

    writer = MemoryManager(
        store=SQLiteMemoryStore(db_path),
        config=MemoryManagerConfig(compaction_enabled=False),
    )
    writer.ingest_turn(
        session_id="session-a",
        user_message="I prefer concise status updates.",
        assistant_message="Noted.",
    )

    reader = MemoryManager(
        store=SQLiteMemoryStore(db_path),
        config=MemoryManagerConfig(compaction_enabled=False),
    )
    snapshot = reader.recall(
        session_id="session-a",
        query="what do i prefer",
        messages=[],
    )

    assert any("User preference:" in rec.content for rec in snapshot.semantic)


def test_compaction_prunes_old_episodic_records() -> None:
    manager = MemoryManager(
        config=MemoryManagerConfig(
            compaction_enabled=True,
            compaction_every_n_turns=1,
            compaction_max_episodic_per_session=3,
            compaction_batch_size=2,
        )
    )
    for idx in range(6):
        manager.ingest_turn(
            session_id="session-a",
            user_message=f"turn {idx} preference note",
            assistant_message=f"response {idx}",
        )

    episodic = manager.store.list_records(
        session_id="session-a",
        levels={MemoryLevel.EPISODIC},
        limit=None,
        newest_first=True,
    )
    semantic = manager.store.list_records(
        session_id="session-a",
        levels={MemoryLevel.SEMANTIC},
        limit=None,
        newest_first=True,
    )

    assert len(episodic) <= 3
    assert any("compaction" in rec.tags for rec in semantic)


def test_lessons_persist_between_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"

    writer = MemoryManager(
        store=SQLiteMemoryStore(db_path),
        config=MemoryManagerConfig(
            compaction_enabled=False,
            lesson_promotion_min_repeats=1,
            lessons_recall_k=4,
        ),
    )
    writer.ingest_turn(
        session_id="session-a",
        user_message="From now on, always include data notes in outputs.",
        assistant_message="Noted.",
    )

    reader = MemoryManager(
        store=SQLiteMemoryStore(db_path),
        config=MemoryManagerConfig(compaction_enabled=False, lessons_recall_k=4),
    )
    snapshot = reader.recall(
        session_id="session-a",
        query="format outputs",
        messages=[],
    )

    assert any("include data notes in outputs" in rec.content for rec in snapshot.lessons)


def test_user_endorsed_resources_persist_between_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"

    writer = MemoryManager(
        store=SQLiteMemoryStore(db_path),
        config=MemoryManagerConfig(compaction_enabled=False),
    )
    writer.ingest_turn(
        session_id="session-a",
        user_message=(
            "Find a current FOMC hawk versus dove breakdown.\n\n"
            "Helpful resources for this:\n"
            "https://itc-m.co/FedPrev"
        ),
        assistant_message="Noted.",
    )

    reader = MemoryManager(
        store=SQLiteMemoryStore(db_path),
        config=MemoryManagerConfig(compaction_enabled=False),
    )
    snapshot = reader.recall(
        session_id="session-b",
        query="FOMC hawk dove",
        messages=[],
    )

    resource_records = [
        rec for rec in snapshot.semantic if rec.metadata.get("source") == "user_endorsed_resource"
    ]

    assert any(rec.metadata.get("url") == "https://itc-m.co/FedPrev" for rec in resource_records)
    assert all(rec.session_id is None for rec in resource_records)
