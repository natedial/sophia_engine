"""Tests for causality computations."""

import json
from datetime import date, timedelta

import numpy as np
import pytest

from sophia_arithmos.computations.causality import GrangerCausality
from sophia_arithmos.core.types import Observation, OutputMode


def _make_observations(
    values: list[float], start: date = date(2024, 1, 1)
) -> list[Observation]:
    return [Observation(date=start + timedelta(days=i), value=v) for i, v in enumerate(values)]


def _dated_json(values: list[float], start: date = date(2024, 1, 1)) -> str:
    """Source series as the JSON list of dated pairs GrangerCausality takes."""
    return json.dumps(
        [
            {"date": (start + timedelta(days=i)).isoformat(), "value": v}
            for i, v in enumerate(values)
        ]
    )


class TestGrangerCausality:
    """Tests for GrangerCausality computation."""

    def test_missing_source_observations_is_an_input_error(self) -> None:
        gc = GrangerCausality()
        np.random.seed(42)
        values = np.cumsum(np.random.randn(50)).tolist()
        data = _make_observations(values)

        with pytest.raises(ValueError, match="source_observations"):
            gc.execute(
                data,
                {"source_series": "inflation", "target_series": "policy", "max_lag": 5},
                OutputMode.SUMMARY,
            )

    def test_malformed_source_observations_is_an_input_error(self) -> None:
        gc = GrangerCausality()
        data = _make_observations(np.cumsum(np.random.randn(50)).tolist())

        with pytest.raises(ValueError, match="JSON-encoded"):
            gc.execute(
                data,
                {
                    "source": "x",
                    "target": "y",
                    "source_observations": "not-json",
                },
                OutputMode.SUMMARY,
            )

    def test_disjoint_dates_fail_with_join_count(self) -> None:
        """Month-start source and month-end target share no dates."""
        gc = GrangerCausality()
        starts = [date(2020 + m // 12, m % 12 + 1, 1) for m in range(40)]
        ends = [d - timedelta(days=1) for d in starts[1:]] + [date(2023, 4, 30)]
        data = [Observation(date=d, value=float(i)) for i, d in enumerate(ends)]
        source = json.dumps(
            [{"date": d.isoformat(), "value": float(i)} for i, d in enumerate(starts)]
        )

        with pytest.raises(ValueError, match="n_joined=0"):
            gc.execute(
                data,
                {"source": "x", "target": "y", "source_observations": source},
                OutputMode.SUMMARY,
            )

    def test_shuffled_source_order_gives_same_result(self) -> None:
        """Pairs are matched by date, so list order cannot change the answer."""
        gc = GrangerCausality()
        rng = np.random.default_rng(7)
        y = np.cumsum(rng.standard_normal(60))
        x = np.cumsum(rng.standard_normal(60))
        data = _make_observations(y.tolist())
        pairs = json.loads(_dated_json(x.tolist()))
        shuffled = list(pairs)
        rng.shuffle(shuffled)

        ordered = gc.execute(
            data,
            {"source": "x", "target": "y", "source_observations": json.dumps(pairs)},
            OutputMode.SUMMARY,
        )
        reordered = gc.execute(
            data,
            {"source": "x", "target": "y", "source_observations": json.dumps(shuffled)},
            OutputMode.SUMMARY,
        )

        assert ordered.summary == reordered.summary

    def test_summary_reports_joined_window(self) -> None:
        gc = GrangerCausality()
        rng = np.random.default_rng(3)
        y = np.cumsum(rng.standard_normal(60))
        x = np.cumsum(rng.standard_normal(50))
        data = _make_observations(y.tolist())
        # Source starts 10 days after the target.
        source = _dated_json(x.tolist(), start=date(2024, 1, 11))

        result = gc.execute(
            data,
            {"source": "x", "target": "y", "source_observations": source},
            OutputMode.SUMMARY,
        )

        summary = result.summary
        assert summary is not None
        assert summary["n_source"] == 50
        assert summary["n_target"] == 60
        assert summary["n_joined"] == 50
        assert summary["n_observations"] == 50
        assert summary["joined_start"] == "2024-01-11"
        assert summary["joined_end"] == "2024-02-29"
        assert summary["frequency"] == "daily"

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
                "source_observations": _dated_json(x.tolist()),
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
        """Test that different source series produce different Granger test results."""
        gc = GrangerCausality()
        np.random.seed(42)
        y = np.cumsum(np.random.randn(50))

        x1 = y[:-1] + np.random.randn(49) * 0.1  # correlated with y
        np.random.seed(123)
        x2 = np.cumsum(np.random.randn(49))  # uncorrelated

        data = _make_observations(y[1:].tolist())

        result1 = gc.execute(
            data,
            {"source": "x1", "target": "y", "source_observations": _dated_json(x1.tolist())},
            OutputMode.SUMMARY,
        )

        result2 = gc.execute(
            data,
            {"source": "x2", "target": "y", "source_observations": _dated_json(x2.tolist())},
            OutputMode.SUMMARY,
        )

        assert result1.summary is not None
        assert result2.summary is not None
        assert result1.summary["method"] == "bivariate_var"
        assert result2.summary["method"] == "bivariate_var"
        assert result1.summary["p_value"] != result2.summary["p_value"]

    def test_backward_compatibility_source_series(self) -> None:
        """Old source_series alias still works when source_observations are present."""
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
                "source_observations": _dated_json(x.tolist()),
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
                    "source_observations": _dated_json([1.0, 2.0, 3.0]),
                    "max_lag": 5,
                },
                OutputMode.SUMMARY,
            )
