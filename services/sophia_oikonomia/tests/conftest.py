"""Pytest fixtures for Sophia Oikonomia."""

import pytest
from fastapi.testclient import TestClient

from sophia_oikonomia.adapters.base import ModelAdapter
from sophia_oikonomia.main import app, runtime, store
from sophia_oikonomia.core.types import (
    InputSnapshotRef,
    ModelDefinition,
    ModelExecutionResult,
    ModelRun,
    ModelTrigger,
    RunStatus,
)


class FakeBistroAdapter(ModelAdapter):
    """Test adapter that avoids external model dependencies."""

    def build_input_snapshot(
        self,
        definition: ModelDefinition,
        trigger: ModelTrigger,
    ) -> InputSnapshotRef:
        return InputSnapshotRef(
            snapshot_id=f"test-snap-{definition.id}",
            as_of=trigger.as_of,
            source_refs=["scrivener:FRED:CPIAUCSL"],
            payload={
                "target_series_id": "CPIAUCSL",
                "target_series": {
                    "series_id": "CPIAUCSL",
                    "provider": "FRED",
                    "metadata": {"external_id": "CPIAUCSL", "name": "Consumer Price Index"},
                    "observations": [
                        {"date": "2024-01-01", "value": 3.1},
                        {"date": "2024-02-01", "value": 3.2},
                        {"date": "2024-03-01", "value": 3.0},
                    ],
                },
                "covariates": [],
            },
            metadata={"adapter_id": definition.execution.adapter_id},
        )

    def execute(
        self,
        definition: ModelDefinition,
        run: ModelRun,
    ) -> ModelExecutionResult:
        return ModelExecutionResult(
            status=RunStatus.SUCCEEDED,
            output_summary={
                "model_id": definition.id,
                "status": "success",
                "forecast_count": 2,
                "first_forecast": {
                    "timestamp": "2026-04-01T00:00:00Z",
                    "point_forecast": 2.9,
                },
                "last_forecast": {
                    "timestamp": "2026-05-01T00:00:00Z",
                    "point_forecast": 2.8,
                },
                "horizon": 2,
                "frequency": "M",
            },
            raw_output={
                "status": "success",
                "results": {
                    "horizon": 2,
                    "frequency": "M",
                    "forecasts": [
                        {"timestamp": "2026-04-01T00:00:00Z", "point_forecast": 2.9},
                        {"timestamp": "2026-05-01T00:00:00Z", "point_forecast": 2.8},
                    ],
                },
            },
            insights=["Inflation is projected to cool over the next two prints."],
            quality_score=0.81,
        )


@pytest.fixture(autouse=True)
def clear_store() -> None:
    """Reset in-memory state before each test."""
    store.reset()
    runtime.adapters.register("bistro", FakeBistroAdapter())


@pytest.fixture
def client() -> TestClient:
    """Test client."""
    return TestClient(app)
