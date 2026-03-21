"""Lossless debugging history exports."""

from sophia.history.manager import LosslessHistoryManager
from sophia.history.store import HistoryStore, SQLiteHistoryStore
from sophia.history.types import (
    HistoryEventRecord,
    HistoryEventType,
    SessionRecap,
    SessionSearchResult,
)

__all__ = [
    "HistoryEventRecord",
    "HistoryEventType",
    "HistoryStore",
    "LosslessHistoryManager",
    "SessionRecap",
    "SessionSearchResult",
    "SQLiteHistoryStore",
]
