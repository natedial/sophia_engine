"""Evaluation metric interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EvaluationMetric(ABC):
    @abstractmethod
    def score(self, *, expected: object, observed: object) -> float: ...
