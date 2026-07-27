"""Compatibility shim for legacy dev_worker imports."""

from sophia.coding_workers import CodingWorkerExecution, CodexCodingWorker, create_coding_worker

DevWorkerExecution = CodingWorkerExecution
CodexDevWorker = CodexCodingWorker

__all__ = ["CodexDevWorker", "DevWorkerExecution", "create_coding_worker"]
