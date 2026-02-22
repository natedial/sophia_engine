"""Background worker for asynchronous memory embedding indexing."""

from __future__ import annotations

import argparse
import logging
import sys

from sophia.config import Settings, get_settings
from sophia.memory import SQLiteMemoryStore, create_memory_store

logger = logging.getLogger(__name__)


def run_index_pass(
    settings: Settings,
    *,
    batch_size: int | None = None,
    max_batches: int | None = None,
) -> dict[str, int]:
    """Run one indexing pass over pending memory records."""
    store = create_memory_store(
        backend=settings.memory_store_backend,
        sqlite_path=settings.memory_store_path,
        semantic_search_enabled=settings.memory_semantic_search_enabled,
        lexical_weight=settings.memory_lexical_weight,
        semantic_weight=settings.memory_semantic_weight,
        embedding_provider=settings.memory_embedding_provider,
        embedding_model=settings.memory_embedding_model,
        embedding_enabled=settings.memory_embedding_enabled,
        embed_episodic=settings.memory_embed_episodic,
        embed_semantic=settings.memory_embed_semantic,
        query_use_embedding_index=settings.memory_query_use_embedding_index,
        embedding_openai_api_key=(
            settings.memory_embedding_openai_api_key or settings.openai_api_key
        ),
        embedding_openai_base_url=settings.memory_embedding_openai_base_url,
        embedding_timeout_sec=settings.memory_embedding_timeout_sec,
        embedding_retry_max_attempts=settings.memory_embedding_retry_max_attempts,
        embedding_retry_base_delay_sec=settings.memory_embedding_retry_base_ms / 1000.0,
        embedding_retry_max_delay_sec=settings.memory_embedding_retry_max_ms / 1000.0,
        embedding_retry_jitter=settings.memory_embedding_retry_jitter,
    )
    if not isinstance(store, SQLiteMemoryStore):
        raise ValueError(
            "Embedding index worker requires MEMORY_STORE_BACKEND=sqlite."
        )

    stats = store.index_pending_embeddings(
        batch_size=batch_size or settings.memory_embedding_batch_size,
        max_batches=max_batches or settings.memory_embedding_max_batches,
    )
    logger.info(
        "memory_index_worker_pass processed=%s ready=%s failed=%s batches=%s backlog_before=%s backlog_after=%s",
        stats.get("processed", 0),
        stats.get("ready", 0),
        stats.get("failed", 0),
        stats.get("batches", 0),
        stats.get("backlog_before", 0),
        stats.get("backlog_after", 0),
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Index pending Sophia memory embeddings"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override embedding batch size",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Override maximum batches processed per run",
    )
    args = parser.parse_args()

    settings = get_settings()
    level = getattr(logging, settings.memory_log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        stats = run_index_pass(
            settings,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
    except Exception as exc:
        print(f"memory-index failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(
        "memory-index completed "
        f"(processed={stats['processed']}, ready={stats['ready']}, "
        f"failed={stats['failed']}, batches={stats['batches']}, "
        f"backlog_before={stats.get('backlog_before', 0)}, "
        f"backlog_after={stats.get('backlog_after', 0)})"
    )


if __name__ == "__main__":
    main()
