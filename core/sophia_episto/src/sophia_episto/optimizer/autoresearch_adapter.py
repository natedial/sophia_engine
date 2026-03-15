"""Reserved adapter surface for an autoresearch-style optimizer loop."""

from __future__ import annotations

from sophia_episto.optimizer.base import ExperimentResult, OptimizationAdapter, ProposedChange


class AutoresearchAdapter(OptimizationAdapter):
    name = "autoresearch"

    def propose(self, program: str) -> list[ProposedChange]:
        return [
            ProposedChange(
                target="playbooks/labor_vs_growth.py",
                summary="Stub proposal surface for offline autoresearch experiments.",
            )
        ]

    def evaluate(self, changes: list[ProposedChange]) -> ExperimentResult:
        return ExperimentResult(
            accepted=False,
            score_delta=0.0,
            notes=("Autoresearch execution is not wired yet.",),
        )
