"""Factory for delegated coding worker backends."""

from __future__ import annotations

from sophia.coding_workers.base import BaseCodingWorker
from sophia.coding_workers.claude_code import ClaudeCodeWorker
from sophia.coding_workers.codex import CodexCodingWorker
from sophia.config import Settings
from sophia.security.filesystem import ReadPolicy, WritePolicy


def create_coding_worker(
    *,
    settings: Settings,
    read_policy: ReadPolicy,
    write_policy: WritePolicy,
    process_factory=None,
) -> BaseCodingWorker:
    """Create the configured coding worker backend."""
    backend = settings.coding_worker_backend.strip().lower() or "codex"
    if backend == "codex":
        return CodexCodingWorker(
            settings=settings,
            read_policy=read_policy,
            write_policy=write_policy,
            process_factory=process_factory,
        )
    if backend == "claude_code":
        return ClaudeCodeWorker(
            settings=settings,
            read_policy=read_policy,
            write_policy=write_policy,
            process_factory=process_factory,
        )
    raise ValueError(f"Unsupported coding worker backend: {settings.coding_worker_backend}")
