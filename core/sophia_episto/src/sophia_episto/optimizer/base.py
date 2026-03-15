"""Optimizer base interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProposedChange:
    target: str
    summary: str


@dataclass(frozen=True)
class ExperimentResult:
    accepted: bool
    score_delta: float
    notes: tuple[str, ...] = ()


class OptimizationAdapter(ABC):
    name: str

    @abstractmethod
    def propose(self, program: str) -> list[ProposedChange]: ...

    @abstractmethod
    def evaluate(self, changes: list[ProposedChange]) -> ExperimentResult: ...
