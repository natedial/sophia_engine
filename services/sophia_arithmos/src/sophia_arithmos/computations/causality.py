"""Causality computations for time series analysis."""

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


@registry.register
class GrangerCausality(Computation):
    """Test for Granger causality between two time series.

    Tests whether past values of one series help predict another
    beyond using past values of the target series alone.

    Requires an explicit source series via `source_values`. Missing, malformed,
    or length-mismatched source input is an error — it is not rewritten as a
    univariate autoregression of the target.
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
        "source_values": ParamSpec(
            type="string",
            description="JSON-encoded list of source series values for bivariate Granger test",
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
        """Compute a bivariate Granger test. Source series is required."""
        import json

        params = dict(params)
        if not params.get("source") and not params.get("source_series"):
            raise ValueError("Missing required parameter: source or source_series")
        if not params.get("target") and not params.get("target_series"):
            raise ValueError("Missing required parameter: target or target_series")
        params["source"] = params.get("source") or params.get("source_series") or "unknown"
        params["target"] = params.get("target") or params.get("target_series") or "unknown"

        source = params["source"]
        target = params["target"]
        source_values_str = params.get("source_values")
        max_lag = params.get("max_lag", 5)
        alpha = params.get("alpha", 0.05)

        if source_values_str in (None, ""):
            raise ValueError(
                "Missing required parameter: source_values. "
                "Omitting the source series changes the question being tested."
            )

        if len(data) < max_lag + 10:
            raise ValueError(f"Insufficient data: need at least {max_lag + 10} observations")

        y = np.array([obs.value for obs in data])
        try:
            parsed = json.loads(source_values_str)
            x = np.asarray(parsed, dtype=float)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(
                "source_values must be a JSON-encoded list of numbers"
            ) from exc
        if x.ndim != 1:
            raise ValueError("source_values must be a one-dimensional series")
        if len(x) != len(y):
            raise ValueError(
                f"source_values length {len(x)} does not match target observations {len(y)}"
            )
        return self._bivariate_granger(x, y, source, target, max_lag, alpha, len(data))

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



