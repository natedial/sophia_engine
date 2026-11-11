"""Injected method runners.

Default production coordination is Oikonomia, which runs the Arithmos
Granger test. Without Oikonomia the runner reports the method unavailable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sophia_episto.research.contracts import (
    EmpiricalResult,
    InputSnapshot,
    MethodCapability,
    QuestionType,
)
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode


GRANGER_METHOD = "granger_predictive"
GRANGER_VERSION = "arithmos-granger-2"  # 2: series joined on date


class MethodRunner(Protocol):
    def capabilities(self) -> list[MethodCapability]:
        ...

    def run(
        self,
        *,
        run_id: str,
        case_id: str,
        hypothesis_id: str | None,
        fingerprint: str,
        method: str,
        question_type: QuestionType,
        snapshot: InputSnapshot,
    ) -> EmpiricalResult:
        ...


class UnavailableRunner:
    """Used when Arithmos is not importable or a method is not installed."""

    def capabilities(self) -> list[MethodCapability]:
        return [
            MethodCapability(
                name=GRANGER_METHOD,
                available=False,
                question_types=[QuestionType.PREDICTIVE, QuestionType.ASSOCIATION],
                required_inputs=["source_observations", "target_observations", "vintage"],
                notes="Arithmos is not available in this process.",
            )
        ]

    def run(self, **kwargs: object) -> EmpiricalResult:
        raise ProtocolError(
            ProtocolErrorCode.METHOD_UNAVAILABLE,
            "Requested method is not available",
            details={"method": kwargs.get("method")},
        )


def default_runner(oikonomia_db: Path | None = None) -> MethodRunner:
    try:
        from sophia_episto.research.oikonomia_runner import OikonomiaMethodRunner

        db_path = oikonomia_db or Path(".sophia/oikonomia/hypothesis-tests.db")
        return OikonomiaMethodRunner(db_path)
    except ImportError:
        return UnavailableRunner()

