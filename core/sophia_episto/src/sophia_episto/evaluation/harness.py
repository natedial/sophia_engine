"""Simple evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass

from sophia_episto.evaluation.cases import EvalCase


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    score: float
    notes: tuple[str, ...] = ()


class EvaluationHarness:
    def run(self, cases: list[EvalCase]) -> list[EvalResult]:
        return [EvalResult(case_id=case.case_id, score=0.0) for case in cases]
