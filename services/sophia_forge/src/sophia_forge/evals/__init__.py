"""Eval corpus and replay support for Sophia Forge."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from sophia_forge.evals.models import (
    EvalCase,
    EvalCaseExport,
    EvalCaseExportRequest,
    EvalCaseExpectation,
    EvalCaseResult,
    EvalCaseReviewRecord,
    EvalCaseReviewRequest,
    EvalCaseStatus,
    EvalReplayRequest,
    EvalRunSummary,
)

__all__ = [
    "EvalCase",
    "EvalCaseExport",
    "EvalCaseExportRequest",
    "EvalCaseExpectation",
    "EvalCaseResult",
    "EvalCaseReviewRecord",
    "EvalCaseReviewRequest",
    "EvalCaseStatus",
    "EvalReplayRequest",
    "EvalReplayRunner",
    "EvalRunSummary",
    "default_corpus_dir",
    "export_eval_case_record",
    "list_eval_cases",
    "review_eval_case",
    "load_eval_cases",
]


def __getattr__(name: str) -> Any:
    if name in {"EvalReplayRunner", "default_corpus_dir", "load_eval_cases"}:
        module = import_module("sophia_forge.evals.runner")
        return getattr(module, name)
    if name == "export_eval_case_record":
        module = import_module("sophia_forge.evals.exporter")
        return getattr(module, name)
    if name in {"list_eval_cases", "review_eval_case"}:
        module = import_module("sophia_forge.evals.curation")
        return getattr(module, name)
    raise AttributeError(name)
