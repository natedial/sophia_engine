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
        strength = max(0.0, 1.0 - best_pvalue) if best_pvalue < alpha else 0.0

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

        strength = 1.0 - p_value if p_value < alpha else 0.0

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


@registry.register
class CausalStrength(Computation):
    """Estimate causal strength between two series using multiple methods."""

    name = "causal_strength"
    description = "Estimate causal strength from source to target using multiple methods"
    params = {
        "source_series": ParamSpec(
            type="string",
            description="ID of the source series",
            required=True,
        ),
        "target_series": ParamSpec(
            type="string",
            description="ID of the target series",
            required=True,
        ),
        "method": ParamSpec(
            type="string",
            description="Method to use: 'regression', 'correlation', 'transfer_entropy'",
            default="regression",
            choices=["regression", "correlation", "transfer_entropy"],
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        """Compute causal strength estimate."""
        source_id = params["source_series"]
        target_id = params["target_series"]
        method = params.get("method", "regression")

        if len(data) < 10:
            raise ValueError(f"Insufficient data: need at least 10 observations")

        values = np.array([obs.value for obs in data])

        if method == "correlation":
            return self._correlation_method(values, source_id, target_id)
        elif method == "transfer_entropy":
            return self._transfer_entropy_method(values, source_id, target_id)
        else:
            return self._regression_method(values, source_id, target_id)

    def _regression_method(
        self,
        values: np.ndarray,
        source_id: str,
        target_id: str,
    ) -> ComputationResult:
        """Use regression to estimate causal strength."""
        lag = 1
        y = values[lag:]
        X = values[:-lag].reshape(-1, 1)
        X = np.column_stack([np.ones(len(X)), X])

        try:
            coeffs, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
            y_pred = X @ coeffs
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
            strength = abs(coeffs[1]) if len(coeffs) > 1 else 0.0
            p_value = 0.05
        except Exception:
            r_squared = 0.0
            strength = 0.0
            p_value = 1.0

        return ComputationResult(
            series=None,
            latest=None,
            summary={
                "source_series": source_id,
                "target_series": target_id,
                "method": "regression",
                "strength": float(strength),
                "r_squared": float(r_squared),
                "coefficient": float(coeffs[1]) if len(coeffs) > 1 else 0.0,
                "p_value": float(p_value),
            },
            metadata={"computation": "causal_strength"},
        )

    def _correlation_method(
        self,
        values: np.ndarray,
        source_id: str,
        target_id: str,
    ) -> ComputationResult:
        """Use correlation of lagged values."""
        lag = 1
        source = values[:-lag]
        target = values[lag:]

        correlation = np.corrcoef(source, target)[0, 1]
        strength = abs(correlation) if not np.isnan(correlation) else 0.0

        return ComputationResult(
            series=None,
            latest=None,
            summary={
                "source_series": source_id,
                "target_series": target_id,
                "method": "correlation",
                "strength": float(strength),
                "correlation": float(correlation) if not np.isnan(correlation) else 0.0,
            },
            metadata={"computation": "causal_strength", "lag": lag},
        )

    def _transfer_entropy_method(
        self,
        values: np.ndarray,
        source_id: str,
        target_id: str,
    ) -> ComputationResult:
        """Estimate transfer entropy (simplified version)."""
        lag = 1
        future = values[lag:]
        present = values[:-lag]

        bins = 5
        hist_ystar = np.histogram2d(future, present, bins=bins)[0]
        hist_y = np.histogram(present, bins=bins)[0]

        p_y = hist_y / hist_y.sum()
        p_ystar_y = hist_ystar / hist_ystar.sum(axis=1, keepdims=True)

        with np.errstate(divide="ignore", invalid="ignore"):
            te = 0.0
            for i in range(bins):
                for j in range(bins):
                    if p_ystar_y[i, j] > 0 and p_y[j] > 0:
                        te += p_ystar_y[i, j] * np.log(p_ystar_y[i, j] / p_y[j])

        strength = max(0.0, te) if not np.isnan(te) else 0.0

        return ComputationResult(
            series=None,
            latest=None,
            summary={
                "source_series": source_id,
                "target_series": target_id,
                "method": "transfer_entropy",
                "strength": float(strength),
                "transfer_entropy": float(te) if not np.isnan(te) else 0.0,
            },
            metadata={"computation": "causal_strength", "lag": lag, "bins": bins},
        )
