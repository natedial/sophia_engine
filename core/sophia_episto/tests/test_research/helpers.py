from __future__ import annotations

from datetime import date, timedelta

from sophia_episto.research.contracts import (
    EmpiricalResult,
    InputSnapshot,
    MethodCapability,
    ObservationPoint,
    QuestionType,
    ResultStatus,
)
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode


class FakeRunner:
    def __init__(
        self,
        *,
        available: bool = True,
        result: EmpiricalResult | None = None,
        error: ProtocolError | None = None,
    ) -> None:
        self.available = available
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def capabilities(self) -> list[MethodCapability]:
        return [
            MethodCapability(
                name="granger_predictive",
                available=self.available,
                question_types=[QuestionType.PREDICTIVE, QuestionType.ASSOCIATION],
                required_inputs=["source_observations", "target_observations", "vintage"],
            )
        ]

    def run(self, **kwargs):
        self.calls.append(kwargs)
        question_type = kwargs["question_type"]
        if question_type in {QuestionType.COUNTERFACTUAL, QuestionType.INTERVENTION}:
            raise ProtocolError(
                ProtocolErrorCode.UNSUPPORTED_QUESTION,
                "No intervention or counterfactual answer is available",
                details={
                    "missing": [
                        "identified_causal_model",
                        "intervention_mechanism",
                    ]
                },
            )
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result.model_copy(
                update={
                    "run_id": kwargs["run_id"],
                    "case_id": kwargs["case_id"],
                    "hypothesis_id": kwargs["hypothesis_id"],
                    "fingerprint": kwargs["fingerprint"],
                    "input_snapshot": kwargs["snapshot"],
                }
            )
        return EmpiricalResult(
            run_id=kwargs["run_id"],
            case_id=kwargs["case_id"],
            hypothesis_id=kwargs["hypothesis_id"],
            fingerprint=kwargs["fingerprint"],
            method=kwargs["method"],
            method_version="fake-1",
            question_type=QuestionType.PREDICTIVE,
            estimand="predictive_granger",
            status=ResultStatus.SUCCEEDED,
            input_snapshot=kwargs["snapshot"],
            estimate=0.42,
            assumptions=["no_causal_identification"],
            scope_limitations=["predictive_association_only", "confounding_unresolved"],
            identification_resolved=False,
        )


def dated_series(start: str, values: list[float]) -> list[ObservationPoint]:
    year, month, day = (int(part) for part in start.split("-"))
    base = date(year, month, day)
    return [
        ObservationPoint(date=(base + timedelta(days=i)).isoformat(), value=value)
        for i, value in enumerate(values)
    ]


def snapshot(vintage: str, source: list[float], target: list[float]) -> InputSnapshot:
    return InputSnapshot(
        vintage=vintage,
        as_of="2026-09-30",
        window_start="2020-01-01",
        window_end="2026-09-30",
        source_series="inflation_surprise",
        target_series="policy_path",
        source_observations=dated_series("2020-01-01", source),
        target_observations=dated_series("2020-01-01", target),
    )
