"""Regression computations."""

from typing import Any

import numpy as np
from scipy import stats

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
class LinearRegression(Computation):
    """Simple linear regression on time series."""

    name = "linear_regression"
    description = "Fit a linear trend line to the series (OLS regression on time index)"
    params = {
        "periods": ParamSpec(
            type="int",
            description="Limit regression to last N periods (0 = all data)",
            default=0,
            min_value=0,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        periods = params.get("periods", 0)

        # Optionally limit to recent data
        if periods > 0 and periods < len(data):
            data = data[-periods:]

        if len(data) < 2:
            raise ValueError(f"Insufficient data: need at least 2, have {len(data)}")

        # Create numeric x values (0, 1, 2, ...) for time index
        x = np.arange(len(data))
        y = np.array([obs.value for obs in data])

        # Perform linear regression
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

        # Generate fitted values
        fitted = slope * x + intercept
        fitted_series = [
            Observation(date=data[i].date, value=float(fitted[i]))
            for i in range(len(data))
        ]

        # Calculate residuals
        residuals = y - fitted

        return ComputationResult(
            series=fitted_series if output == OutputMode.FULL else None,
            latest=fitted_series[-1] if fitted_series else None,
            summary={
                "slope": float(slope),
                "intercept": float(intercept),
                "r_squared": float(r_value**2),
                "r_value": float(r_value),
                "p_value": float(p_value),
                "std_err": float(std_err),
                "residual_std": float(np.std(residuals)),
            },
            metadata={
                "computation": "linear_regression",
                "n_observations": len(data),
                "start_date": data[0].date.isoformat(),
                "end_date": data[-1].date.isoformat(),
            },
        )


@registry.register
class MultiRegression(Computation):
    """Multiple regression with additional series as independent variables.

    Note: This computation expects data in a special format where each observation
    contains additional values for the independent variables. For v1, we support
    a simplified interface where the user can specify the additional series inline.
    """

    name = "multi_regression"
    description = "Multiple linear regression (OLS) with additional independent variables"
    params = {
        "include_time": ParamSpec(
            type="bool",
            description="Include time index as an independent variable",
            default=True,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        """Multi-regression requires additional data passed via extended observation format.

        For now, this performs simple regression with time as the only independent variable.
        Future versions will support passing multiple series.
        """
        import statsmodels.api as sm

        include_time = params.get("include_time", True)

        if len(data) < 2:
            raise ValueError(f"Insufficient data: need at least 2, have {len(data)}")

        y = np.array([obs.value for obs in data])

        # Build X matrix
        if include_time:
            X = np.arange(len(data)).reshape(-1, 1)
        else:
            # If no time and no other variables, fall back to constant model
            X = np.ones((len(data), 1))

        # Add constant for intercept
        X = sm.add_constant(X)

        # Fit OLS model
        model = sm.OLS(y, X)
        results = model.fit()

        # Generate fitted values
        fitted = results.fittedvalues
        fitted_series = [
            Observation(date=data[i].date, value=float(fitted[i]))
            for i in range(len(data))
        ]

        return ComputationResult(
            series=fitted_series if output == OutputMode.FULL else None,
            latest=fitted_series[-1] if fitted_series else None,
            summary={
                "r_squared": float(results.rsquared),
                "adj_r_squared": float(results.rsquared_adj),
                "f_statistic": float(results.fvalue) if results.fvalue else None,
                "f_pvalue": float(results.f_pvalue) if results.f_pvalue else None,
                "aic": float(results.aic),
                "bic": float(results.bic),
                "coefficients": {
                    f"beta_{i}": float(c) for i, c in enumerate(results.params)
                },
                "std_errors": {
                    f"se_{i}": float(se) for i, se in enumerate(results.bse)
                },
                "p_values": {
                    f"p_{i}": float(p) for i, p in enumerate(results.pvalues)
                },
            },
            metadata={
                "computation": "multi_regression",
                "n_observations": len(data),
                "n_variables": X.shape[1] - 1,  # Exclude constant
                "include_time": include_time,
            },
        )


@registry.register
class RollingRegression(Computation):
    """Rolling window linear regression."""

    name = "rolling_regression"
    description = "Calculate rolling linear regression over a moving window"
    params = {
        "window": ParamSpec(
            type="int",
            description="Number of periods in the rolling window",
            required=True,
            min_value=3,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        window = params["window"]

        if len(data) < window:
            raise ValueError(f"Insufficient data: need {window}, have {len(data)}")

        slopes = []
        r_squared_series = []

        for i in range(window - 1, len(data)):
            window_data = data[i - window + 1 : i + 1]
            x = np.arange(window)
            y = np.array([obs.value for obs in window_data])

            slope, intercept, r_value, _, _ = stats.linregress(x, y)

            slopes.append(Observation(date=data[i].date, value=float(slope)))
            r_squared_series.append(Observation(date=data[i].date, value=float(r_value**2)))

        return ComputationResult(
            series=slopes if output == OutputMode.FULL else None,
            latest=slopes[-1] if slopes else None,
            summary={
                "latest_slope": slopes[-1].value if slopes else None,
                "latest_r_squared": r_squared_series[-1].value if r_squared_series else None,
                "avg_slope": float(np.mean([s.value for s in slopes])) if slopes else None,
                "avg_r_squared": float(np.mean([r.value for r in r_squared_series])) if r_squared_series else None,
            },
            metadata={
                "computation": "rolling_regression",
                "window": window,
                "n_windows": len(slopes),
            },
        )
