"""Module-level corpus singleton — initialised at startup, shared across requests."""

from __future__ import annotations

import logging
from pathlib import Path

from sophia_tholos.search.engine import HybridSearchEngine

logger = logging.getLogger(__name__)

_engine: HybridSearchEngine | None = None


def init_engine(
    db_path: str,
    npz_path: str,
    model_name: str = "all-MiniLM-L6-v2",
    *,
    semantic_enabled: bool = True,
    semantic_local_files_only: bool = True,
    model_cache_dir: str | None = None,
) -> None:
    """Eagerly initialise the search engine (loads npz into RAM)."""
    global _engine
    _engine = None

    db = Path(db_path)
    npz = Path(npz_path)

    if not db.exists():
        logger.warning("Corpus DB not found at %s — starting without corpus", db)
        return
    if not npz.exists():
        logger.warning("Embeddings NPZ not found at %s — semantic search disabled", npz)

    logger.info("Loading corpus: db=%s  npz=%s  model=%s", db, npz, model_name)
    try:
        _engine = HybridSearchEngine(
            db_path=db,
            npz_path=npz if npz.exists() else None,
            model_name=model_name,
            semantic_enabled=semantic_enabled,
            semantic_local_files_only=semantic_local_files_only,
            model_cache_dir=model_cache_dir,
        )
    except Exception:
        if npz.exists():
            logger.exception(
                "Failed to load embeddings from %s — retrying with lexical-only corpus",
                npz,
            )
            try:
                _engine = HybridSearchEngine(
                    db_path=db,
                    npz_path=None,
                    model_name=model_name,
                    semantic_enabled=semantic_enabled,
                    semantic_local_files_only=semantic_local_files_only,
                    model_cache_dir=model_cache_dir,
                )
            except Exception:
                logger.exception("Failed to initialize corpus from %s", db)
                _engine = None
                return
        else:
            logger.exception("Failed to initialize corpus from %s", db)
            _engine = None
            return
    logger.info(
        "Corpus ready: %d chunks, npz_dims=%s",
        _engine.chunk_count,
        _engine.npz_dims,
    )


def get_engine() -> HybridSearchEngine | None:
    """Return the singleton engine, or None if corpus is unavailable."""
    return _engine
