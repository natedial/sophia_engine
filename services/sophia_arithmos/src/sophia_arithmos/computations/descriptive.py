"""Descriptive statistics computations."""

from decimal import Decimal
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
class Mean(Computation):
    """Calculate the arithmetic mean of a series."""

    name = "mean"
    description = "Calculate the arithmetic mean (average) of the series"
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        values = [obs.value for obs in data]
        mean_val = float(np.mean(values))

        return ComputationResult(
            latest=Observation(date=data[-1].date, value=mean_val),
            summary={"mean": mean_val, "n": len(values)},
            metadata={"computation": "arithmetic_mean"},
        )


@registry.register
class Median(Computation):
    """Calculate the median of a series."""

    name = "median"
    description = "Calculate the median (middle value) of the series"
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        values = [obs.value for obs in data]
        median_val = float(np.median(values))

        return ComputationResult(
            latest=Observation(date=data[-1].date, value=median_val),
            summary={"median": median_val, "n": len(values)},
            metadata={"computation": "median"},
        )


@registry.register
class StdDev(Computation):
    """Calculate the standard deviation of a series."""

    name = "std_dev"
    description = "Calculate the standard deviation of the series"
    params = {
        "ddof": ParamSpec(
            type="int",
            description="Delta degrees of freedom (0 for population, 1 for sample)",
            default=1,
            min_value=0,
            max_value=1,
        )
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        values = [obs.value for obs in data]
        ddof = params.get("ddof", 1)
        if len(values) <= ddof:
            raise ValueError(
                f"Insufficient data: need > {ddof} for std_dev, have {len(values)}"
            )
        std_val = float(np.std(values, ddof=ddof))

        return ComputationResult(
            latest=Observation(date=data[-1].date, value=std_val),
            summary={"std_dev": std_val, "variance": std_val**2, "n": len(values)},
            metadata={"computation": "standard_deviation", "ddof": ddof},
        )


@registry.register
class Percentile(Computation):
    """Calculate a percentile of a series."""

    name = "percentile"
    description = "Calculate a specific percentile of the series"
    params = {
        "q": ParamSpec(
            type="float",
            description="Percentile to compute (0-100)",
            required=True,
            min_value=0,
            max_value=100,
        )
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        values = [obs.value for obs in data]
        q = params["q"]
        percentile_val = float(np.percentile(values, q))

        return ComputationResult(
            latest=Observation(date=data[-1].date, value=percentile_val),
            summary={"percentile": percentile_val, "q": q, "n": len(values)},
            metadata={"computation": "percentile"},
        )


@registry.register
class MinMax(Computation):
    """Calculate min and max of a series."""

    name = "min_max"
    description = "Calculate the minimum and maximum values of the series"
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        values = [obs.value for obs in data]
        min_val = float(np.min(values))
        max_val = float(np.max(values))
        range_val = max_val - min_val

        # Find dates of min/max
        min_idx = int(np.argmin(values))
        max_idx = int(np.argmax(values))

        return ComputationResult(
            summary={
                "min": min_val,
                "max": max_val,
                "range": range_val,
                "min_date": data[min_idx].date.isoformat(),
                "max_date": data[max_idx].date.isoformat(),
                "n": len(values),
            },
            metadata={"computation": "min_max"},
        )


@registry.register
class DescriptiveStats(Computation):
    """Calculate comprehensive descriptive statistics."""

    name = "descriptive_stats"
    description = "Calculate comprehensive descriptive statistics (mean, median, std, min, max, quartiles)"
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        values = [obs.value for obs in data]
        arr = np.array(values)
        if len(values) < 2:
            raise ValueError("Insufficient data: need at least 2 for descriptive_stats")

        return ComputationResult(
            summary={
                "n": len(values),
                "mean": float(np.mean(arr)),
                "median": float(np.median(arr)),
                "std_dev": float(np.std(arr, ddof=1)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "q25": float(np.percentile(arr, 25)),
                "q75": float(np.percentile(arr, 75)),
                "iqr": float(np.percentile(arr, 75) - np.percentile(arr, 25)),
            },
            metadata={"computation": "descriptive_stats"},
        )
