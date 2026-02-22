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
