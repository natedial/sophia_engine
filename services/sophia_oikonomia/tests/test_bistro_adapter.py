"""Unit tests for the promoted BISTRO adapter."""

from datetime import UTC, datetime

from sophia_oikonomia.adapters import BistroAdapter
from sophia_oikonomia.clients import ObservationPoint, SeriesSnapshot
from sophia_oikonomia.core.types import (
    DataDependency,
    DependencyKind,
    ExecutionSpec,
    ModelDefinition,
    ModelFamily,
    ModelTrigger,
    TriggerType,
)


class FakeScrivenerClient:
    """Minimal fake client for snapshot construction."""

    def build_series_snapshot(
        self,
        series_id: str,
        *,
        source: str | None = None,
        days: int | None = None,
        limit: int | None = None,
    ) -> SeriesSnapshot:
        _ = days, limit
        return SeriesSnapshot(
            external_id=series_id,
            source=source,
            metadata={"external_id": series_id, "source": source},
            observations=[
                ObservationPoint(date="2024-01-01", value=2.9),
                ObservationPoint(date="2024-02-01", value=3.0),
                ObservationPoint(date="2024-03-01", value=3.1),
            ],
        )


def test_bistro_adapter_builds_snapshot_from_scrivener_series() -> None:
    adapter = BistroAdapter(
        scrivener=FakeScrivenerClient(),
        market_models_root="/tmp/market_models",
    )
    definition = ModelDefinition(
        id="bistro-v1",
        name="BISTRO Macro Forecast",
        family=ModelFamily.MACRO,
        owner="rates-research",
        dependencies=[
            DataDependency(
                source="scrivener",
                provider="FRED",
                kind=DependencyKind.SERIES,
                series_id="CPIAUCSL",
            ),
            DataDependency(
                source="scrivener",
                provider="FRED",
                kind=DependencyKind.SERIES,
                series_id="FEDFUNDS",
            ),
        ],
        execution=ExecutionSpec(
            adapter_id="bistro",
            default_parameters={"lookback_days": 365},
        ),
        metadata={"target_series_id": "CPIAUCSL"},
    )
    trigger = ModelTrigger(
        trigger_type=TriggerType.DATA_REFRESH,
        as_of=datetime(2026, 3, 18, 17, 0, tzinfo=UTC),
        source="scrivener",
        series_ids=["CPIAUCSL"],
    )

    snapshot = adapter.build_input_snapshot(definition, trigger)

    assert snapshot.payload["target_series_id"] == "CPIAUCSL"
    assert snapshot.payload["target_series"]["series_id"] == "CPIAUCSL"
    assert len(snapshot.payload["target_series"]["observations"]) == 3
    assert len(snapshot.payload["covariates"]) == 1
    assert snapshot.source_refs == [
        "scrivener:FRED:CPIAUCSL",
        "scrivener:FRED:FEDFUNDS",
    ]
