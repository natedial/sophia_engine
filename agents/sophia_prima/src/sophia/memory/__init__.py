"""Layered memory framework exports."""

from sophia.memory.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    create_embedding_provider,
)
from sophia.memory.manager import MemoryManager, MemoryManagerConfig
from sophia.memory.store import (
    InMemoryMemoryStore,
    MemoryStore,
    SQLiteMemoryStore,
    create_memory_store,
)
from sophia.memory.types import (
    MEMORY_LEVEL_SPECS,
    FrozenMemorySnapshot,
    MemoryLevel,
    MemoryLevelSpec,
    MemoryMatch,
    MemoryRecord,
    MemorySnapshot,
)

__all__ = [
    "FrozenMemorySnapshot",
    "InMemoryMemoryStore",
    "MEMORY_LEVEL_SPECS",
    "MemoryLevel",
    "MemoryLevelSpec",
    "MemoryManager",
    "MemoryManagerConfig",
    "MemoryMatch",
    "MemoryRecord",
    "MemorySnapshot",
    "MemoryStore",
    "SQLiteMemoryStore",
    "create_memory_store",
    "EmbeddingProvider",
    "HashEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "create_embedding_provider",
]
