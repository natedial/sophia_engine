from pathlib import Path

from sophia.config import Settings
from sophia.memory import MemoryLevel, MemoryRecord, SQLiteMemoryStore, create_memory_store
from sophia.memory_index_worker import run_index_pass


def test_index_pending_embeddings_updates_status_and_vectors(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(db_path, embed_episodic=False, embed_semantic=True)
    store.add(
        MemoryRecord(
            level=MemoryLevel.SEMANTIC,
            session_id="session-a",
            content="User preference: concise responses.",
        )
    )

    stats = store.index_pending_embeddings(batch_size=10, max_batches=2)

    assert stats["processed"] == 1
    assert stats["ready"] == 1
    with store._connect() as conn:  # noqa: SLF001 - narrow internal assertion
        ready_count = conn.execute(
            "SELECT COUNT(*) FROM memory_records WHERE embedding_status = 'ready'"
        ).fetchone()[0]
        vector_count = conn.execute(
            "SELECT COUNT(*) FROM memory_embeddings WHERE model = ?",
            ("hash-v1",),
        ).fetchone()[0]
    assert ready_count == 1
    assert vector_count == 1


class _FakeEmbeddingProvider:
    @property
    def name(self) -> str:
        return "fake-v1"

    def embed_texts(self, texts: list[str]) -> list[dict[int, float]]:
        vectors: list[dict[int, float]] = []
        for text in texts:
            lower = text.lower()
            if "alpha" in lower:
                vectors.append({0: 1.0})
            elif "beta" in lower:
                vectors.append({1: 1.0})
            else:
                vectors.append({2: 1.0})
        return vectors


def test_custom_embedding_provider_drives_retrieval(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(
        db_path,
        semantic_search_enabled=False,
        embedding_provider=_FakeEmbeddingProvider(),
        embedding_model="fake-v1",
    )
    rec_alpha = MemoryRecord(
        level=MemoryLevel.SEMANTIC,
        session_id="session-a",
        content="Alpha strategy details",
    )
    rec_beta = MemoryRecord(
        level=MemoryLevel.SEMANTIC,
        session_id="session-a",
        content="Beta strategy details",
    )
    store.add(rec_alpha)
    store.add(rec_beta)
    store.index_pending_embeddings(batch_size=10, max_batches=2)

    matches = store.query(
        session_id="session-a",
        query="alpha",
        levels={MemoryLevel.SEMANTIC},
        limit=2,
    )
    assert matches[0].record.id == rec_alpha.id


def test_query_can_use_indexed_embeddings_when_local_semantic_off(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(
        db_path,
        semantic_search_enabled=False,
        embed_episodic=False,
        embed_semantic=True,
        query_use_embedding_index=True,
    )
    rec_buy = MemoryRecord(
        level=MemoryLevel.SEMANTIC,
        session_id="session-a",
        content="We should buy treasuries quickly on dislocations.",
    )
    rec_sell = MemoryRecord(
        level=MemoryLevel.SEMANTIC,
        session_id="session-a",
        content="We should sell oil futures on rallies.",
    )
    store.add(rec_buy)
    store.add(rec_sell)
    store.index_pending_embeddings(batch_size=10, max_batches=2)

    matches = store.query(
        session_id="session-a",
        query="purchase bonds fast when markets dislocate",
        levels={MemoryLevel.SEMANTIC},
        limit=2,
    )

    assert matches[0].record.id == rec_buy.id
    assert matches[0].score > matches[1].score


def test_openai_provider_requires_api_key() -> None:
    try:
        create_memory_store(
            backend="sqlite",
            sqlite_path=":memory:",
            embedding_enabled=True,
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            embedding_openai_api_key="",
        )
    except ValueError as exc:
        assert "requires an API key" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing OpenAI embedding key")


def test_worker_runs_one_index_pass(tmp_path: Path) -> None:
    settings = Settings(
        memory_store_backend="sqlite",
        memory_store_path=tmp_path / "memory.db",
        memory_embedding_enabled=True,
        memory_embed_episodic=False,
        memory_embed_semantic=True,
    )
    store = SQLiteMemoryStore(settings.memory_store_path, embed_episodic=False, embed_semantic=True)
    store.add(
        MemoryRecord(
            level=MemoryLevel.SEMANTIC,
            session_id="session-a",
            content="Project decision: prefer weekly rollups.",
        )
    )

    stats = run_index_pass(settings, batch_size=10, max_batches=2)

    assert stats["processed"] == 1
    assert stats["ready"] == 1
