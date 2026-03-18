"""Promoted adapter for the external BISTRO model wrapper."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..clients import ScrivenerClient
from ..core.types import (
    DependencyKind,
    InputSnapshotRef,
    ModelDefinition,
    ModelExecutionResult,
    ModelRun,
    ModelTrigger,
    RunStatus,
)
from .base import ModelAdapter


class BistroAdapter(ModelAdapter):
    """Bridge from Oikonomia to the external BISTRO harness."""

    def __init__(
        self,
        scrivener: ScrivenerClient,
        market_models_root: str,
        default_lookback_days: int = 3650,
        harness_factory: Any | None = None,
    ) -> None:
        self.scrivener = scrivener
        self.market_models_root = Path(market_models_root)
        self.default_lookback_days = default_lookback_days
        self._harness_factory = harness_factory

    def build_input_snapshot(
        self,
        definition: ModelDefinition,
        trigger: ModelTrigger,
    ) -> InputSnapshotRef:
        series_dependencies = [
            dependency
            for dependency in definition.dependencies
            if dependency.kind == DependencyKind.SERIES and dependency.series_id
        ]
        if not series_dependencies:
            raise ValueError(f"BISTRO model '{definition.id}' requires at least one series dependency")

        lookback_days = int(
            definition.execution.default_parameters.get("lookback_days", self.default_lookback_days)
        )
        limit = definition.execution.default_parameters.get("series_limit")
        target_series_id = str(
            definition.metadata.get("target_series_id", series_dependencies[0].series_id)
        )

        source_refs: list[str] = []
        target_payload: dict[str, Any] | None = None
        covariates: list[dict[str, Any]] = []

        for dependency in series_dependencies:
            series_id = dependency.series_id
            assert series_id is not None
            snapshot = self.scrivener.build_series_snapshot(
                series_id,
                source=dependency.provider,
                days=lookback_days,
                limit=int(limit) if limit is not None else None,
            )
            payload = {
                "series_id": snapshot.external_id,
                "provider": dependency.provider,
                "metadata": snapshot.metadata,
                "observations": [
                    {"date": point.date, "value": point.value}
                    for point in snapshot.observations
                ],
            }
            provider_ref = dependency.provider or "default"
            source_refs.append(f"{dependency.source}:{provider_ref}:{series_id}")
            if series_id == target_series_id:
                target_payload = payload
            else:
                covariates.append(payload)

        if target_payload is None:
            raise ValueError(
                f"BISTRO model '{definition.id}' target series '{target_series_id}' was not found in dependencies"
            )

        return InputSnapshotRef(
            snapshot_id=f"snap-{definition.id}-{trigger.as_of.strftime('%Y%m%d%H%M%S')}",
            as_of=trigger.as_of,
            source_refs=source_refs,
            payload={
                "target_series_id": target_series_id,
                "target_series": target_payload,
                "covariates": covariates,
                "lookback_days": lookback_days,
                "trigger_payload": trigger.payload,
            },
            metadata={
                "adapter_id": definition.execution.adapter_id,
                "series_count": len(source_refs),
            },
        )

    def execute(
        self,
        definition: ModelDefinition,
        run: ModelRun,
    ) -> ModelExecutionResult:
        harness = self._build_harness(definition)
        request = self._build_execution_request(definition, run)
        output = harness.execute(request)
        payload = output.model_dump(mode="json")
        forecasts = payload.get("results", {}).get("forecasts", [])

        summary = {
            "model_id": definition.id,
            "status": payload.get("status"),
            "forecast_count": len(forecasts),
            "first_forecast": forecasts[0] if forecasts else None,
            "last_forecast": forecasts[-1] if forecasts else None,
            "frequency": payload.get("results", {}).get("frequency"),
            "horizon": payload.get("results", {}).get("horizon"),
            "warnings": payload.get("execution_metadata", {}).get("warnings", []),
            "errors": payload.get("errors", []),
        }

        insights = [
            f"{definition.name} produced {len(forecasts)} forecast points as of {run.input_snapshot.as_of.date().isoformat()}."
        ]
        if forecasts:
            first_point = forecasts[0]
            insights.append(
                f"Near-term forecast is {first_point.get('point_forecast')} for {first_point.get('timestamp')}."
            )

        status = RunStatus.SUCCEEDED if payload.get("status") != "error" else RunStatus.FAILED
        error = None
        if status == RunStatus.FAILED:
            errors = payload.get("errors", [])
            error = "; ".join(str(item) for item in errors) if errors else "Model execution failed"

        return ModelExecutionResult(
            status=status,
            output_summary=summary,
            raw_output=payload,
            insights=insights,
            quality_score=None,
            error=error,
        )

    def _build_harness(self, definition: ModelDefinition) -> Any:
        if self._harness_factory is not None:
            return self._harness_factory(definition)

        if not self.market_models_root.exists():
            raise FileNotFoundError(f"market_models root not found: {self.market_models_root}")

        market_models_root_str = str(self.market_models_root)
        if market_models_root_str not in sys.path:
            sys.path.insert(0, market_models_root_str)

        from model_harness.models.bistro.harness import BistroHarness

        model_path = definition.execution.artifact_path
        device = str(definition.execution.default_parameters.get("device", "cpu"))
        return BistroHarness(model_path=model_path, device=device)

    def _build_execution_request(self, definition: ModelDefinition, run: ModelRun) -> Any:
        market_models_root_str = str(self.market_models_root)
        if market_models_root_str not in sys.path:
            sys.path.insert(0, market_models_root_str)

        from model_harness import ExecutionRequest, ModelInput, OutputCriteria, TimeSeriesPoint

        snapshot_payload = run.input_snapshot.payload
        target_series = snapshot_payload["target_series"]
        covariates = snapshot_payload.get("covariates", [])

        target_points = [
            TimeSeriesPoint(
                timestamp=datetime.fromisoformat(point["date"]).replace(tzinfo=UTC),
                value=float(point["value"]),
                variable=str(target_series["series_id"]),
            )
            for point in target_series["observations"]
        ]
        covariate_points = [
            TimeSeriesPoint(
                timestamp=datetime.fromisoformat(point["date"]).replace(tzinfo=UTC),
                value=float(point["value"]),
                variable=str(covariate["series_id"]),
            )
            for covariate in covariates
            for point in covariate["observations"]
        ]

        parameters = dict(definition.execution.default_parameters)
        parameters.update(run.trigger.payload.get("parameters", {}))

        return ExecutionRequest(
            model_id=definition.id,
            task_type="forecast",
            data=ModelInput(
                time_series=target_points,
                covariates=covariate_points or None,
                static_features={
                    "target_series_id": target_series["series_id"],
                    "source_refs": run.input_snapshot.source_refs,
                },
            ),
            parameters=parameters,
            output_criteria=OutputCriteria(include_metadata=True),
        )
