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

    For true Granger causality between two distinct series, this computation
    accepts the source series via the 'source_values' parameter (list of floats).
    If only data is provided, tests autoregressive predictive power within that series.
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
        """Compute Granger causality test.

        If source_values is provided, performs bivariate Granger test between source and target.
        Otherwise performs univariate autoregression test on the target series.
        """
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

        if len(data) < max_lag + 10:
            raise ValueError(f"Insufficient data: need at least {max_lag + 10} observations")

        y = np.array([obs.value for obs in data])

        if source_values_str:
            try:
                import json

                x = np.array(json.loads(source_values_str))
            except (json.JSONDecodeError, TypeError):
                x = None
        else:
            x = None

        if x is not None and len(x) == len(y):
            return self._bivariate_granger(x, y, source, target, max_lag, alpha, len(data))
        else:
            return self._univariate_granger(y, source, target, max_lag, alpha, len(data))

    def _univariate_granger(
        self,
        y: np.ndarray,
        source: str,
        target: str,
        max_lag: int,
        alpha: float,
        n_obs: int,
    ) -> ComputationResult:
        """Test autoregressive predictive power within a single series."""
        best_lag = 1
        best_pvalue = 1.0
        best_stat = 0.0

        for lag in range(1, max_lag + 1):
            y_current = y[lag:]
            X_lagged = y[:-lag]

            if len(y_current) < 10:
                continue

            X_with_const = np.column_stack([np.ones(len(X_lagged)), X_lagged])

            try:
                coeffs, _, _, _ = np.linalg.lstsq(X_with_const, y_current, rcond=None)
                y_pred = X_with_const @ coeffs
                ss_res = np.sum((y_current - y_pred) ** 2)
                ss_tot = np.sum((y_current - np.mean(y_current)) ** 2)

                if ss_tot == 0:
                    continue

                r_squared = 1 - (ss_res / ss_tot)
                n = len(y_current)
                k = 2
                if r_squared > 0:
                    f_stat = (r_squared / (k - 1)) / ((1 - r_squared) / (n - k))
                    p_value = 1 - _f_cdf(f_stat, k - 1, n - k)
                else:
                    p_value = 1.0
                    f_stat = 0.0

                if p_value < best_pvalue:
                    best_pvalue = p_value
                    best_lag = lag
                    best_stat = f_stat

            except Exception:
                continue

        is_causal = best_pvalue < alpha
        # Strength = incremental predictive contribution, bounded [0,1].
        # Only reported when the effect is statistically detected; else 0.
        strength = 0.0
        if is_causal and len(y) > best_lag + 5:
            y_t = y[best_lag:]
            y_lag = y[:-best_lag]
            if y_lag.std(ddof=1) > 0 and y_t.std(ddof=1) > 0:
                r = float(np.corrcoef(y_lag, y_t)[0, 1])
                strength = max(0.0, min(1.0, r * r))

        return ComputationResult(
            series=None,
            latest=None,
            summary={
                "source_series": source,
                "target_series": target,
                "test_statistic": float(best_stat),
                "p_value": float(best_pvalue),
                "is_granger_causal": is_causal,
                "strength": float(strength),
                "best_lag": best_lag,
                "max_lag": max_lag,
                "alpha": alpha,
                "n_observations": n_obs,
                "method": "univariate_autoregression",
                "note": "Univariate test - source_values not provided, testing autoregressive power",
            },
            metadata={
                "computation": "granger_causality",
                "interpretation": "Univariate autoregression test. Provide source_values for bivariate Granger test.",
            },
        )

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


def _f_cdf(f_stat: float, dfn: int, dfd: int) -> float:
    """Simplified F-distribution CDF approximation."""
    if f_stat <= 0:
        return 0.0
    if dfd <= 0:
        return 0.0
    try:
        from scipy import stats

        return float(stats.f.cdf(f_stat, dfn, dfd))
    except Exception:
        x = dfn * f_stat / (dfn * f_stat + dfd)
        return x if x <= 1 else 1.0


