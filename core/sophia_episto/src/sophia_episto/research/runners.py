"""Injected method runners. Slice A executes Granger in-process via Arithmos."""

from __future__ import annotations

from typing import Protocol

from sophia_episto.research.contracts import (
    EmpiricalResult,
    InputSnapshot,
    MethodCapability,
    QuestionType,
    ResultStatus,
)
from sophia_episto.research.errors import ProtocolError, ProtocolErrorCode


GRANGER_METHOD = "granger_predictive"
GRANGER_VERSION = "arithmos-granger-1"


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


class InProcessArithmosRunner:
    def capabilities(self) -> list[MethodCapability]:
        available = _arithmos_importable()
        return [
            MethodCapability(
                name=GRANGER_METHOD,
                available=available,
                question_types=[QuestionType.PREDICTIVE, QuestionType.ASSOCIATION],
                required_inputs=[
                    "source_observations",
                    "target_observations",
                    "vintage",
                    "dated_window",
                ],
                notes=(
                    "Predictive Granger test. Does not identify a causal effect "
                    "or support intervention claims."
                ),
            )
        ]

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
        if method != GRANGER_METHOD:
            raise ProtocolError(
                ProtocolErrorCode.METHOD_UNAVAILABLE,
                f"Unknown method: {method}",
                details={"method": method},
            )
        if question_type in {QuestionType.INTERVENTION, QuestionType.COUNTERFACTUAL}:
            raise ProtocolError(
                ProtocolErrorCode.UNSUPPORTED_QUESTION,
                "Granger is a predictive test and cannot answer intervention "
                "or counterfactual questions",
                details={
                    "method": method,
                    "question_type": question_type.value,
                    "missing": [
                        "identified_causal_model",
                        "intervention_mechanism",
                        "confounder_adjustment",
                    ],
                },
            )
        if question_type == QuestionType.IDENTIFIED_CAUSAL:
            raise ProtocolError(
                ProtocolErrorCode.UNSUPPORTED_QUESTION,
                "No identified causal estimator is registered",
                details={"method": method},
            )

        try:
            from sophia_arithmos.computations.causality import GrangerCausality
            from sophia_arithmos.core.types import Observation, OutputMode
        except ImportError as exc:
            raise ProtocolError(
                ProtocolErrorCode.METHOD_UNAVAILABLE,
                "Arithmos Granger runner is not importable",
            ) from exc

        if not snapshot.source_observations:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "source_observations are required; omitting them changes the question",
            )
        if not snapshot.target_observations:
            raise ProtocolError(
                ProtocolErrorCode.INVALID_REQUEST,
                "target_observations are required",
            )

        import json
        from datetime import date

        def _obs(points: list) -> list:
            parsed = []
            for point in points:
                parsed.append(
                    Observation(date=date.fromisoformat(point.date), value=point.value)
                )
            return parsed

        source_values = [point.value for point in snapshot.source_observations]
        target = _obs(snapshot.target_observations)
        params = {
            "source": snapshot.source_series or "source",
            "target": snapshot.target_series or "target",
            "source_values": json.dumps(source_values),
        }
        window = {
            "start": snapshot.window_start,
            "end": snapshot.window_end,
            "vintage": snapshot.vintage,
            "as_of": snapshot.as_of,
        }
        try:
            computed = GrangerCausality().execute(target, params, OutputMode.SUMMARY)
            summary = computed.summary or {}
            return EmpiricalResult(
                run_id=run_id,
                case_id=case_id,
                hypothesis_id=hypothesis_id,
                fingerprint=fingerprint,
                method=method,
                method_version=GRANGER_VERSION,
                question_type=QuestionType.PREDICTIVE,
                estimand="predictive_granger",
                status=ResultStatus.SUCCEEDED,
                input_snapshot=snapshot,
                estimate=summary.get("strength"),
                diagnostics=summary,
                assumptions=[
                    "stationary_or_preprocessed_series",
                    "linear_var",
                    "no_causal_identification",
                ],
                scope_limitations=[
                    "predictive_association_only",
                    "confounding_unresolved",
                    f"observation_window={window}",
                ],
                identification_resolved=False,
            )
        except ValueError as exc:
            return EmpiricalResult(
                run_id=run_id,
                case_id=case_id,
                hypothesis_id=hypothesis_id,
                fingerprint=fingerprint,
                method=method,
                method_version=GRANGER_VERSION,
                question_type=QuestionType.PREDICTIVE,
                estimand="predictive_granger",
                status=ResultStatus.FAILED,
                input_snapshot=snapshot,
                failures=[str(exc)],
                assumptions=["source_and_target_required"],
                scope_limitations=["test_did_not_run"],
                identification_resolved=False,
            )


def default_runner() -> MethodRunner:
    if _arithmos_importable():
        return InProcessArithmosRunner()
    return UnavailableRunner()


def _arithmos_importable() -> bool:
    try:
        from sophia_arithmos.computations.causality import GrangerCausality  # noqa: F401
    except ImportError:
        return False
    return True
