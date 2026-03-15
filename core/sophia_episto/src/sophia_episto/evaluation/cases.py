"""Evaluation case models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    question: str
    required_indicator_families: tuple[str, ...] = ()
