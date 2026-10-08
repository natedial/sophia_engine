"""Adapter for Episto hypothesis-test requests.

Coordinates Arithmos numerical methods. A successful computation is not
publication eligibility and is not identified causal evidence.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from ..core.types import (
    InputSnapshotRef,
    ModelDefinition,
    ModelExecutionResult,
    ModelRun,
    ModelTrigger,
    RunStatus,
)
from .base import ModelAdapter

ADAPTER_ID = "hypothesis_test"
GRANGER_VERSION = "arithmos-granger-1"


class HypothesisTestAdapter(ModelAdapter):
    def build_input_snapshot(
        self,
        definition: ModelDefinition,
        trigger: ModelTrigger,
    ) -> InputSnapshotRef:
        payload = trigger.payload or {}
        fingerprint = str(payload.get("fingerprint") or f"snap-{trigger.as_of.isoformat()}")
        as_of_raw = payload.get("as_of") or trigger.as_of
        if isinstance(as_of_raw, str):
            as_of = datetime.fromisoformat(as_of_raw.replace("Z", "+00:00"))
        else:
            as_of = trigger.as_of
        return InputSnapshotRef(
            snapshot_id=fingerprint,
            as_of=as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC),
            source_refs=[str(payload.get("case_id") or "")],
            payload=payload.get("input") or {},
            metadata={
                "fingerprint": fingerprint,
                "method": payload.get("method"),
                "hypothesis_id": payload.get("hypothesis_id"),
                "epistemic_support": False,
            },
        )

    def execute(self, definition: ModelDefinition, run: ModelRun) -> ModelExecutionResult:
        payload = run.trigger.payload or {}
        method = str(payload.get("method") or "granger_predictive")
        question_type = str(payload.get("question_type") or "predictive")
        if question_type in {"intervention", "counterfactual", "identified_causal"}:
            return ModelExecutionResult(
                status=RunStatus.FAILED,
                error=(
                    "Hypothesis-test adapter cannot answer intervention or "
                    "counterfactual questions"
                ),
                output_summary={
                    "status": "failed",
                    "method": method,
                    "question_type": question_type,
                    "failures": ["unsupported_question"],
                    "missing": [
                        "identified_causal_model",
                        "intervention_mechanism",
                    ],
                    "identification_resolved": False,
                },
            )
        if method != "granger_predictive":
            return ModelExecutionResult(
                status=RunStatus.FAILED,
                error=f"Unknown method: {method}",
                output_summary={
                    "status": "unavailable",
                    "method": method,
                    "failures": [f"unknown_method:{method}"],
                    "identification_resolved": False,
                },
            )
        return _run_granger(run.input_snapshot.payload, method, question_type)


def _run_granger(
    snapshot: dict[str, Any],
    method: str,
    question_type: str,
) -> ModelExecutionResult:
    try:
        from sophia_arithmos.computations.causality import GrangerCausality
        from sophia_arithmos.core.types import Observation, OutputMode
    except ImportError as exc:
        return ModelExecutionResult(
            status=RunStatus.FAILED,
            error="Arithmos Granger runner is not importable",
            output_summary={
                "status": "unavailable",
                "method": method,
                "failures": [str(exc)],
                "identification_resolved": False,
            },
        )

    source_obs = snapshot.get("source_observations") or []
    target_obs = snapshot.get("target_observations") or []
    if not source_obs:
        return ModelExecutionResult(
            status=RunStatus.FAILED,
            error="source_observations are required; omitting them changes the question",
            output_summary={
                "status": "failed",
                "method": method,
                "failures": ["source_observations_required"],
                "identification_resolved": False,
            },
        )
    if not target_obs:
        return ModelExecutionResult(
            status=RunStatus.FAILED,
            error="target_observations are required",
            output_summary={
                "status": "failed",
                "method": method,
                "failures": ["target_observations_required"],
                "identification_resolved": False,
            },
        )

    target = [
        Observation(date=date.fromisoformat(point["date"]), value=float(point["value"]))
        for point in target_obs
    ]
    source_values = [float(point["value"]) for point in source_obs]
    params = {
        "source": snapshot.get("source_series") or "source",
        "target": snapshot.get("target_series") or "target",
        "source_values": json.dumps(source_values),
    }
    window = {
        "start": snapshot.get("window_start"),
        "end": snapshot.get("window_end"),
        "vintage": snapshot.get("vintage"),
        "as_of": snapshot.get("as_of"),
    }
    try:
        computed = GrangerCausality().execute(target, params, OutputMode.SUMMARY)
        summary = computed.summary or {}
        return ModelExecutionResult(
            status=RunStatus.SUCCEEDED,
            output_summary={
                "status": "succeeded",
                "method": method,
                "method_version": GRANGER_VERSION,
                "question_type": "predictive",
                "estimand": "predictive_granger",
                "estimate": summary.get("strength"),
                "diagnostics": summary,
                "assumptions": [
                    "stationary_or_preprocessed_series",
                    "linear_var",
                    "no_causal_identification",
                ],
                "scope_limitations": [
                    "predictive_association_only",
                    "confounding_unresolved",
                    f"observation_window={window}",
                ],
                "failures": [],
                "identification_resolved": False,
            },
            insights=["predictive_granger_only"],
        )
    except ValueError as exc:
        return ModelExecutionResult(
            status=RunStatus.FAILED,
            error=str(exc),
            output_summary={
                "status": "failed",
                "method": method,
                "method_version": GRANGER_VERSION,
                "question_type": question_type,
                "estimand": "predictive_granger",
                "failures": [str(exc)],
                "assumptions": ["source_and_target_required"],
                "scope_limitations": ["test_did_not_run"],
                "identification_resolved": False,
            },
        )
