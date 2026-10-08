"""Tests for causality computations."""

import json
from datetime import date, timedelta

import numpy as np
import pytest

from sophia_arithmos.computations.causality import GrangerCausality
from sophia_arithmos.core.types import Observation, OutputMode


def _make_observations(values: list[float]) -> list[Observation]:
    base = date(2024, 1, 1)
    return [Observation(date=base + timedelta(days=i), value=v) for i, v in enumerate(values)]


class TestGrangerCausality:
    """Tests for GrangerCausality computation."""

    def test_missing_source_values_is_an_input_error(self) -> None:
        gc = GrangerCausality()
        np.random.seed(42)
        values = np.cumsum(np.random.randn(50)).tolist()
        data = _make_observations(values)

        with pytest.raises(ValueError, match="source_values"):
            gc.execute(
                data,
                {"source_series": "inflation", "target_series": "policy", "max_lag": 5},
                OutputMode.SUMMARY,
            )

    def test_malformed_source_values_is_an_input_error(self) -> None:
        gc = GrangerCausality()
        data = _make_observations(np.cumsum(np.random.randn(50)).tolist())

        with pytest.raises(ValueError, match="JSON-encoded"):
            gc.execute(
                data,
                {
                    "source": "x",
                    "target": "y",
                    "source_values": "not-json",
                },
                OutputMode.SUMMARY,
            )

    def test_mismatched_source_length_is_an_input_error(self) -> None:
        gc = GrangerCausality()
        data = _make_observations([float(i) for i in range(40)])

        with pytest.raises(ValueError, match="length"):
            gc.execute(
                data,
                {
                    "source": "x",
                    "target": "y",
                    "source_values": json.dumps([1.0, 2.0, 3.0]),
                },
                OutputMode.SUMMARY,
            )

    def test_bivariate_var_with_correlated_source(self) -> None:
        """Test bivariate VAR with correlated source series."""
        gc = GrangerCausality()
        np.random.seed(42)
        y = np.cumsum(np.random.randn(50))
        x = y[:-1] + np.random.randn(49) * 0.1  # correlated with y

        data = _make_observations(y[1:].tolist())

        result = gc.execute(
            data,
            {
                "source": "x",
                "target": "y",
                "source_values": json.dumps(x.tolist()),
                "max_lag": 5,
                "alpha": 0.05,
            },
            OutputMode.SUMMARY,
        )

        assert result.summary is not None
        assert result.summary["method"] == "bivariate_var"
        assert result.summary["source_series"] == "x"
        assert result.summary["target_series"] == "y"
        assert "p_value" in result.summary

    def test_bivariate_var_different_sources_produce_different_results(self) -> None:
        """Test that different source_values produce different Granger test results."""
        gc = GrangerCausality()
        np.random.seed(42)
        y = np.cumsum(np.random.randn(50))

        x1 = y[:-1] + np.random.randn(49) * 0.1  # correlated with y
        np.random.seed(123)
        x2 = np.cumsum(np.random.randn(49))  # uncorrelated

        data = _make_observations(y[1:].tolist())

        result1 = gc.execute(
            data,
            {"source": "x1", "target": "y", "source_values": json.dumps(x1.tolist())},
            OutputMode.SUMMARY,
        )

        result2 = gc.execute(
            data,
            {"source": "x2", "target": "y", "source_values": json.dumps(x2.tolist())},
            OutputMode.SUMMARY,
        )

        assert result1.summary is not None
        assert result2.summary is not None
        assert result1.summary["method"] == "bivariate_var"
        assert result2.summary["method"] == "bivariate_var"
        assert result1.summary["p_value"] != result2.summary["p_value"]

    def test_backward_compatibility_source_series(self) -> None:
        """Old source_series alias still works when source_values are present."""
        gc = GrangerCausality()
        np.random.seed(42)
        y = np.cumsum(np.random.randn(50))
        x = np.cumsum(np.random.randn(50))
        data = _make_observations(y.tolist())

        result = gc.execute(
            data,
            {
                "source_series": "inflation",
                "target_series": "policy",
                "source_values": json.dumps(x.tolist()),
            },
            OutputMode.SUMMARY,
        )

        assert result.summary is not None
        assert result.summary["source_series"] == "inflation"
        assert result.summary["target_series"] == "policy"
        assert result.summary["method"] == "bivariate_var"

    def test_insufficient_data_raises(self) -> None:
        """Test that insufficient data raises ValueError."""
        gc = GrangerCausality()
        data = _make_observations([1.0, 2.0, 3.0])  # Only 3 observations

        with pytest.raises(ValueError, match="Insufficient data"):
            gc.execute(
                data,
                {
                    "source": "x",
                    "target": "y",
                    "source_values": json.dumps([1.0, 2.0, 3.0]),
                    "max_lag": 5,
                },
                OutputMode.SUMMARY,
            )
