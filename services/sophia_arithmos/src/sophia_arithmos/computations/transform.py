"""Transformation computations."""

import math
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
class PercentChange(Computation):
    """Calculate period-over-period percentage change."""

    name = "percent_change"
    description = "Calculate percentage change from previous period"
    params = {
        "periods": ParamSpec(
            type="int",
            description="Number of periods to look back for change calculation",
            default=1,
            min_value=1,
        ),
    }
    precision_type = PrecisionType.PERCENT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        periods = params.get("periods", 1)
        if len(data) <= periods:
            raise ValueError(f"Insufficient data: need > {periods}, have {len(data)}")
        results = []

        for i in range(periods, len(data)):
            prev_value = data[i - periods].value
            if prev_value != 0:
                pct_change = ((data[i].value - prev_value) / prev_value) * 100
                results.append(Observation(date=data[i].date, value=pct_change))

        if not results:
            raise ValueError("No valid percent_change results: all prior values were zero")

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "percent_change",
                "periods": periods,
                "points_computed": len(results),
            },
        )


@registry.register
class Difference(Computation):
    """Calculate period-over-period difference."""

    name = "difference"
    description = "Calculate absolute difference from previous period"
    params = {
        "periods": ParamSpec(
            type="int",
            description="Number of periods to look back for difference calculation",
            default=1,
            min_value=1,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        periods = params.get("periods", 1)
        if len(data) <= periods:
            raise ValueError(f"Insufficient data: need > {periods}, have {len(data)}")
        results = []

        for i in range(periods, len(data)):
            diff = data[i].value - data[i - periods].value
            results.append(Observation(date=data[i].date, value=diff))

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "difference",
                "periods": periods,
                "points_computed": len(results),
            },
        )


@registry.register
class LogTransform(Computation):
    """Apply natural log transformation."""

    name = "log_transform"
    description = "Apply natural logarithm transformation to the series"
    precision_type = PrecisionType.RATIO

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        results = []
        skipped = 0

        for obs in data:
            if obs.value > 0:
                log_val = math.log(obs.value)
                results.append(Observation(date=obs.date, value=log_val))
            else:
                skipped += 1

        if not results:
            raise ValueError("Log transform requires positive values")

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "log_transform",
                "points_computed": len(results),
                "points_skipped": skipped,
            },
        )


@registry.register
class Cumulative(Computation):
    """Calculate cumulative sum or product."""

    name = "cumulative"
    description = "Calculate cumulative sum or cumulative product of the series"
    params = {
        "method": ParamSpec(
            type="str",
            description="Cumulative method: 'sum' or 'product'",
            default="sum",
            choices=["sum", "product"],
        ),
        "start_value": ParamSpec(
            type="float",
            description="Starting value (0 for sum, 1 for product)",
            default=None,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        method = params.get("method", "sum")
        start = params.get("start_value")

        if start is None:
            start = 0.0 if method == "sum" else 1.0

        results = []
        cumulative = start

        for obs in data:
            if method == "sum":
                cumulative += obs.value
            else:  # product
                cumulative *= obs.value
            results.append(Observation(date=obs.date, value=cumulative))

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            summary={
                "start_value": start,
                "final_value": cumulative,
            },
            metadata={
                "computation": "cumulative",
                "method": method,
            },
        )


@registry.register
class Normalize(Computation):
    """Normalize series to a base value."""

    name = "normalize"
    description = "Normalize series to a base value (index to 100, z-score, etc.)"
    params = {
        "method": ParamSpec(
            type="str",
            description="Normalization method: 'index' (base=100), 'zscore', 'minmax'",
            default="index",
            choices=["index", "zscore", "minmax"],
        ),
        "base_value": ParamSpec(
            type="float",
            description="Base value for index normalization",
            default=100.0,
        ),
    }
    precision_type = PrecisionType.INDEX

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        method = params.get("method", "index")
        base_value = params.get("base_value", 100.0)

        values = np.array([obs.value for obs in data])
        results = []

        if method == "index":
            # Normalize to first value = base
            if values[0] != 0:
                normalized = (values / values[0]) * base_value
            else:
                normalized = values
        elif method == "zscore":
            # Z-score normalization
            mean = np.mean(values)
            std = np.std(values)
            if std != 0:
                normalized = (values - mean) / std
            else:
                normalized = values - mean
        else:  # minmax
            # Min-max normalization to [0, 1]
            min_val = np.min(values)
            max_val = np.max(values)
            if max_val != min_val:
                normalized = (values - min_val) / (max_val - min_val)
            else:
                normalized = np.zeros_like(values)

        results = [
            Observation(date=data[i].date, value=float(normalized[i]))
            for i in range(len(data))
        ]

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "normalize",
                "method": method,
                "base_value": base_value if method == "index" else None,
            },
        )


@registry.register
class MovingAverage(Computation):
    """Calculate simple moving average."""

    name = "moving_average"
    description = "Calculate simple moving average (SMA) over a rolling window"
    params = {
        "window": ParamSpec(
            type="int",
            description="Number of periods in the moving average window",
            required=True,
            min_value=2,
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

        values = np.array([obs.value for obs in data])
        ma = np.convolve(values, np.ones(window) / window, mode="valid")

        # Moving average starts at index (window - 1)
        results = [
            Observation(date=data[i + window - 1].date, value=float(ma[i]))
            for i in range(len(ma))
        ]

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "moving_average",
                "window": window,
                "points_computed": len(results),
            },
        )
