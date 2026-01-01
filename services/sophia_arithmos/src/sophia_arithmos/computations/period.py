"""Period comparison computations (YoY, MoM, lookups)."""

from datetime import date, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta

from ..core.base import Computation
from ..core.registry import registry
from ..core.types import (
    ComputationResult,
    Observation,
    OutputMode,
    ParamSpec,
    PrecisionType,
)


def find_observation_for_date(
    data: list[Observation],
    target_date: date,
    tolerance_days: int = 7,
) -> Observation | None:
    """Find an observation closest to target date within tolerance."""
    best_match = None
    best_delta = timedelta(days=tolerance_days + 1)

    for obs in data:
        delta = abs(obs.date - target_date)
        if delta <= timedelta(days=tolerance_days) and delta < best_delta:
            best_match = obs
            best_delta = delta

    return best_match


@registry.register
class YoYChange(Computation):
    """Calculate year-over-year change."""

    name = "yoy_change"
    description = "Calculate year-over-year absolute change"
    params = {
        "tolerance_days": ParamSpec(
            type="int",
            description="Days tolerance when matching dates across years",
            default=7,
            min_value=0,
            max_value=30,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        tolerance = params.get("tolerance_days", 7)
        results = []

        for obs in data:
            year_ago_date = obs.date - relativedelta(years=1)
            year_ago_obs = find_observation_for_date(data, year_ago_date, tolerance)

            if year_ago_obs:
                change = obs.value - year_ago_obs.value
                results.append(Observation(date=obs.date, value=change))

        if not results:
            raise ValueError("No matching prior-year observations within tolerance")

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "yoy_change",
                "tolerance_days": tolerance,
                "points_computed": len(results),
            },
        )


@registry.register
class YoYPercent(Computation):
    """Calculate year-over-year percentage change."""

    name = "yoy_percent"
    description = "Calculate year-over-year percentage change"
    params = {
        "tolerance_days": ParamSpec(
            type="int",
            description="Days tolerance when matching dates across years",
            default=7,
            min_value=0,
            max_value=30,
        ),
    }
    precision_type = PrecisionType.PERCENT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        tolerance = params.get("tolerance_days", 7)
        results = []

        for obs in data:
            year_ago_date = obs.date - relativedelta(years=1)
            year_ago_obs = find_observation_for_date(data, year_ago_date, tolerance)

            if year_ago_obs and year_ago_obs.value != 0:
                pct_change = ((obs.value - year_ago_obs.value) / year_ago_obs.value) * 100
                results.append(Observation(date=obs.date, value=pct_change))

        if not results:
            raise ValueError("No valid prior-year observations within tolerance")

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "yoy_percent",
                "tolerance_days": tolerance,
                "points_computed": len(results),
            },
        )


@registry.register
class MoMChange(Computation):
    """Calculate month-over-month change."""

    name = "mom_change"
    description = "Calculate month-over-month absolute change"
    params = {
        "tolerance_days": ParamSpec(
            type="int",
            description="Days tolerance when matching dates across months",
            default=5,
            min_value=0,
            max_value=15,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        tolerance = params.get("tolerance_days", 5)
        results = []

        for obs in data:
            month_ago_date = obs.date - relativedelta(months=1)
            month_ago_obs = find_observation_for_date(data, month_ago_date, tolerance)

            if month_ago_obs:
                change = obs.value - month_ago_obs.value
                results.append(Observation(date=obs.date, value=change))

        if not results:
            raise ValueError("No matching prior-month observations within tolerance")

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "mom_change",
                "tolerance_days": tolerance,
                "points_computed": len(results),
            },
        )


@registry.register
class MoMPercent(Computation):
    """Calculate month-over-month percentage change."""

    name = "mom_percent"
    description = "Calculate month-over-month percentage change"
    params = {
        "tolerance_days": ParamSpec(
            type="int",
            description="Days tolerance when matching dates across months",
            default=5,
            min_value=0,
            max_value=15,
        ),
    }
    precision_type = PrecisionType.PERCENT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        tolerance = params.get("tolerance_days", 5)
        results = []

        for obs in data:
            month_ago_date = obs.date - relativedelta(months=1)
            month_ago_obs = find_observation_for_date(data, month_ago_date, tolerance)

            if month_ago_obs and month_ago_obs.value != 0:
                pct_change = ((obs.value - month_ago_obs.value) / month_ago_obs.value) * 100
                results.append(Observation(date=obs.date, value=pct_change))

        if not results:
            raise ValueError("No valid prior-month observations within tolerance")

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "mom_percent",
                "tolerance_days": tolerance,
                "points_computed": len(results),
            },
        )


@registry.register
class PeriodLookup(Computation):
    """Lookup value from a specific period ago."""

    name = "period_lookup"
    description = "Lookup the value from N periods (months, quarters, years) ago"
    params = {
        "n": ParamSpec(
            type="int",
            description="Number of periods to look back",
            required=True,
            min_value=1,
        ),
        "period_type": ParamSpec(
            type="str",
            description="Type of period: 'month', 'quarter', 'year'",
            default="year",
            choices=["month", "quarter", "year"],
        ),
        "tolerance_days": ParamSpec(
            type="int",
            description="Days tolerance when matching dates",
            default=7,
            min_value=0,
            max_value=30,
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        n = params["n"]
        period_type = params.get("period_type", "year")
        tolerance = params.get("tolerance_days", 7)

        # Get the most recent observation
        current = data[-1]

        # Calculate the target date
        if period_type == "month":
            target_date = current.date - relativedelta(months=n)
        elif period_type == "quarter":
            target_date = current.date - relativedelta(months=n * 3)
        else:  # year
            target_date = current.date - relativedelta(years=n)

        # Find the observation
        past_obs = find_observation_for_date(data, target_date, tolerance)

        if past_obs:
            return ComputationResult(
                latest=past_obs,
                summary={
                    "current_date": current.date.isoformat(),
                    "current_value": current.value,
                    "lookup_date": past_obs.date.isoformat(),
                    "lookup_value": past_obs.value,
                    "change": current.value - past_obs.value,
                },
                metadata={
                    "computation": "period_lookup",
                    "periods_back": n,
                    "period_type": period_type,
                },
            )
        raise ValueError(f"No data found for {n} {period_type}(s) ago")
