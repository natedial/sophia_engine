"""Causality computations for time series analysis."""

import json
from datetime import date
from typing import Any

import numpy as np

from ..core.base import Computation
from ..core.registry import registry
from ..core.types import (
    ComputationResult,
    Observation,
    OutputMode,
    ParamSpec,
    PrecisionType,
)
from .alignment import inner_join_on_date


@registry.register
class GrangerCausality(Computation):
    """Test for Granger causality between two time series.

    Tests whether past values of one series help predict another
    beyond using past values of the target series alone.

    Requires an explicit dated source series via `source_observations`. The
    source and target are inner-joined on date; pairs are never matched by
    list position. Missing or malformed source input, duplicate dates, mixed
    frequencies, or too short an overlap is an error. Nothing is rewritten as
    a univariate autoregression of the target.
    """

    name = "granger_causality"
    description = "Test for Granger causality from source to target series"
    params = {
        "source": ParamSpec(
            type="string",
            description="Source series name (alias: source_series)",
            required=False,
        ),
        "source_series": ParamSpec(
            type="string",
            description="Source series name (alias: source)",
            required=False,
        ),
        "target": ParamSpec(
            type="string",
            description="Target series name (alias: target_series)",
            required=False,
        ),
        "target_series": ParamSpec(
            type="string",
            description="Target series name (alias: target)",
            required=False,
        ),
        "source_observations": ParamSpec(
            type="string",
            description=(
                'JSON list of dated source points, [{"date": "YYYY-MM-DD", "value": 1.0}, ...]; '
                "joined to the target on date"
            ),
            required=False,
        ),
        "max_lag": ParamSpec(
            type="int",
            description="Maximum number of lags to test",
            default=5,
            min_value=1,
            max_value=20,
        ),
        "alpha": ParamSpec(
            type="float",
            description="Significance level for rejecting null hypothesis",
            default=0.05,
            min_value=0.001,
            max_value=0.2,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        """Compute a bivariate Granger test on the dates both series share."""
        params = dict(params)
        if not params.get("source") and not params.get("source_series"):
            raise ValueError("Missing required parameter: source or source_series")
        if not params.get("target") and not params.get("target_series"):
            raise ValueError("Missing required parameter: target or target_series")
        params["source"] = params.get("source") or params.get("source_series") or "unknown"
        params["target"] = params.get("target") or params.get("target_series") or "unknown"

        source = params["source"]
        target = params["target"]
        source_json = params.get("source_observations")
        max_lag = params.get("max_lag", 5)
        alpha = params.get("alpha", 0.05)

        if source_json in (None, ""):
            raise ValueError(
                "Missing required parameter: source_observations. "
                "Omitting the source series changes the question being tested."
            )
        source_obs = _parse_dated_series(source_json)

        joined = inner_join_on_date(source_obs, data)
        n_joined = len(joined.dates)
        if n_joined < max_lag + 10:
            raise ValueError(
                f"Insufficient data: need at least {max_lag + 10} observations on "
                f"shared dates, have n_joined={n_joined} "
                f"(source {len(source_obs)}, target {len(data)})"
            )

        result = self._bivariate_granger(
            np.asarray(joined.source, dtype=float),
            np.asarray(joined.target, dtype=float),
            source,
            target,
            max_lag,
            alpha,
            n_joined,
        )
        if result.summary is not None:
            result.summary.update(
                {
                    "n_source": len(source_obs),
                    "n_target": len(data),
                    "n_joined": n_joined,
                    "joined_start": joined.dates[0].isoformat(),
                    "joined_end": joined.dates[-1].isoformat(),
                    "frequency": joined.frequency,
                }
            )
        return result

    def _bivariate_granger(
        self,
        x: np.ndarray,
        y: np.ndarray,
        source: str,
        target: str,
        max_lag: int,
        alpha: float,
        n_obs: int,
    ) -> ComputationResult:
        """Test bivariate Granger causality from x to y."""
        from statsmodels.tsa.vector_ar.var_model import VAR

        if len(x) != len(y):
            raise ValueError("Source and target series must have same length")

        combined = np.column_stack([y, x])
        model = VAR(combined)

        lag_order = min(max_lag, len(combined) // 2)
        if lag_order < 1:
            raise ValueError("Insufficient data for VAR model")

        try:
            result = model.fit(lag_order)
            test_result = result.test_causality(0, 1)
            test_statistic = float(test_result.test_statistic)
            p_value = float(test_result.pvalue)
            is_causal = p_value < alpha
        except Exception:
            test_statistic = 0.0
            p_value = 1.0
            is_causal = False

        # Strength = partial R², the incremental variance in y explained by
        # lagged x beyond y's own lags. Derived from the Granger F-stat:
        #   partial_R² = F·df_num / (F·df_num + df_denom)
        # Bounded [0, 1). Reported only when the effect is detected; else 0.
        strength = 0.0
        if is_causal and test_statistic > 0:
            df_num = lag_order
            df_denom = max(n_obs - 2 * lag_order - 1, 1)
            f_df = test_statistic * df_num
            strength = float(f_df / (f_df + df_denom))

        return ComputationResult(
            series=None,
            latest=None,
            summary={
                "source_series": source,
                "target_series": target,
                "test_statistic": test_statistic,
                "p_value": p_value,
                "is_granger_causal": is_causal,
                "strength": strength,
                "best_lag": lag_order,
                "max_lag": max_lag,
                "alpha": alpha,
                "n_observations": n_obs,
                "method": "bivariate_var",
            },
            metadata={
                "computation": "granger_causality",
                "interpretation": "Bivariate Granger causality test using VAR model.",
            },
        )


def _parse_dated_series(source_json: str) -> list[Observation]:
    """Parse `source_observations`: a JSON list of {"date", "value"} objects."""
    try:
        parsed = json.loads(source_json)
        return [
            Observation(date=date.fromisoformat(point["date"]), value=float(point["value"]))
            for point in parsed
        ]
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        raise ValueError(
            'source_observations must be a JSON-encoded list of {"date", "value"} objects'
        ) from exc
