"""Module-level corpus singleton — initialised at startup, shared across requests."""

from __future__ import annotations

import logging
from pathlib import Path

from sophia_tholos.search.engine import HybridSearchEngine

logger = logging.getLogger(__name__)

_engine: HybridSearchEngine | None = None


def init_engine(db_path: str, npz_path: str, model_name: str = "all-MiniLM-L6-v2") -> None:
    """Eagerly initialise the search engine (loads npz into RAM)."""
    global _engine

    db = Path(db_path)
    npz = Path(npz_path)

    if not db.exists():
        logger.warning("Corpus DB not found at %s — starting without corpus", db)
        return
    if not npz.exists():
        logger.warning("Embeddings NPZ not found at %s — semantic search disabled", npz)

    logger.info("Loading corpus: db=%s  npz=%s  model=%s", db, npz, model_name)
    _engine = HybridSearchEngine(db_path=db, npz_path=npz if npz.exists() else None, model_name=model_name)
    logger.info(
        "Corpus ready: %d chunks, npz_dims=%s",
        _engine.chunk_count,
        _engine.npz_dims,
    )


def get_engine() -> HybridSearchEngine | None:
    """Return the singleton engine, or None if corpus is unavailable."""
    return _engine
