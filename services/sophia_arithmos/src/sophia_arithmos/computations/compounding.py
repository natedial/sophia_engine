"""Compounding and annualization computations."""

from decimal import Decimal
from typing import Any

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
class AnnualizeMoM(Computation):
    """Convert month-over-month rate to annualized rate."""

    name = "annualize_mom"
    description = "Convert month-over-month percentage change to annualized rate"
    params = {
        "compound": ParamSpec(
            type="bool",
            description="Use compound (True) or simple (False) annualization",
            default=True,
        )
    }
    precision_type = PrecisionType.RATE

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        compound = params.get("compound", True)
        results = []

        for obs in data:
            mom_rate = Decimal(str(obs.value)) / 100  # Convert percentage to decimal

            if compound:
                # (1 + r)^12 - 1
                annualized = ((1 + mom_rate) ** 12 - 1) * 100
            else:
                # r * 12
                annualized = mom_rate * 12 * 100

            results.append(Observation(date=obs.date, value=float(annualized)))

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "annualize_mom",
                "method": "compound" if compound else "simple",
                "periods_per_year": 12,
            },
        )


@registry.register
class AnnualizeQoQ(Computation):
    """Convert quarter-over-quarter rate to annualized rate."""

    name = "annualize_qoq"
    description = "Convert quarter-over-quarter percentage change to annualized rate"
    params = {
        "compound": ParamSpec(
            type="bool",
            description="Use compound (True) or simple (False) annualization",
            default=True,
        )
    }
    precision_type = PrecisionType.RATE

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        compound = params.get("compound", True)
        results = []

        for obs in data:
            qoq_rate = Decimal(str(obs.value)) / 100

            if compound:
                # (1 + r)^4 - 1
                annualized = ((1 + qoq_rate) ** 4 - 1) * 100
            else:
                annualized = qoq_rate * 4 * 100

            results.append(Observation(date=obs.date, value=float(annualized)))

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "annualize_qoq",
                "method": "compound" if compound else "simple",
                "periods_per_year": 4,
            },
        )


@registry.register
class CompoundDailyRate(Computation):
    """Compound a daily rate over N days to get annualized equivalent."""

    name = "compound_daily_rate"
    description = "Compound a daily rate over N days (e.g., overnight rate over a year)"
    params = {
        "days": ParamSpec(
            type="int",
            description="Number of days to compound over",
            default=365,
            min_value=1,
            max_value=366,
        ),
        "day_count": ParamSpec(
            type="int",
            description="Day count convention (360 or 365)",
            default=360,
            choices=[360, 365],
        ),
    }
    precision_type = PrecisionType.RATE

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        days = params.get("days", 365)
        day_count = params.get("day_count", 365)
        results = []

        for obs in data:
            # Daily rate as decimal
            daily_rate = Decimal(str(obs.value)) / 100 / day_count

            # Compound: (1 + r/n)^n - 1
            compounded = ((1 + daily_rate) ** days - 1) * 100

            results.append(Observation(date=obs.date, value=float(compounded)))

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "compound_daily_rate",
                "days": days,
                "day_count_convention": day_count,
            },
        )


@registry.register
class Deannualize(Computation):
    """Convert an annualized rate to a periodic rate."""

    name = "deannualize"
    description = "Convert an annualized rate to monthly, quarterly, or daily equivalent"
    params = {
        "periods": ParamSpec(
            type="int",
            description="Number of periods per year (12=monthly, 4=quarterly, 365=daily)",
            required=True,
            min_value=1,
            max_value=365,
        ),
        "compound": ParamSpec(
            type="bool",
            description="Use compound (True) or simple (False) conversion",
            default=True,
        ),
    }
    precision_type = PrecisionType.RATE

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        periods = params["periods"]
        compound = params.get("compound", True)
        results = []

        for obs in data:
            annual_rate = Decimal(str(obs.value)) / 100

            if compound:
                # (1 + r)^(1/n) - 1
                periodic = ((1 + annual_rate) ** (Decimal(1) / periods) - 1) * 100
            else:
                periodic = annual_rate / periods * 100

            results.append(Observation(date=obs.date, value=float(periodic)))

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "deannualize",
                "periods_per_year": periods,
                "method": "compound" if compound else "simple",
            },
        )


@registry.register
class AnnualizeDays(Computation):
    """Annualize a rate that applies to N days."""

    name = "annualize_days"
    description = "Annualize a rate that applies to a specific number of days"
    params = {
        "days": ParamSpec(
            type="int",
            description="Number of days the input rate applies to",
            required=True,
            min_value=1,
            max_value=365,
        ),
        "day_count": ParamSpec(
            type="int",
            description="Day count convention (360 or 365)",
            default=365,
            choices=[360, 365],
        ),
    }
    precision_type = PrecisionType.RATE

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        days = params["days"]
        day_count = params.get("day_count", 365)
        results = []

        for obs in data:
            # Input is a rate for N days (as percentage)
            period_rate = Decimal(str(obs.value)) / 100

            # Annualize: (1 + r)^(365/days) - 1
            annualized = ((1 + period_rate) ** (Decimal(day_count) / days) - 1) * 100

            results.append(Observation(date=obs.date, value=float(annualized)))

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "annualize_days",
                "days": days,
                "day_count_convention": day_count,
            },
        )


@registry.register
class CompoundRates(Computation):
    """Compound multiple period rates together."""

    name = "compound_rates"
    description = "Compound multiple rates together and optionally annualize the result. Input rates can be annualized rates (default) or period rates."
    params = {
        "input_annualized": ParamSpec(
            type="bool",
            description="If True (default), input rates are annualized and will be converted to period rates first",
            default=True,
        ),
        "annualize_output": ParamSpec(
            type="bool",
            description="Annualize the compounded result",
            default=True,
        ),
        "day_count": ParamSpec(
            type="int",
            description="Day count convention (360 or 365)",
            default=365,
            choices=[360, 365],
        ),
    }
    precision_type = PrecisionType.RATE

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        """Compound rates from data series.

        Each observation's value is a rate (percentage). The period for each rate
        is inferred from the date difference to the next observation.

        If input_annualized=True (default), input rates are treated as annualized
        rates and converted to period rates before compounding.
        """
        input_annualized = params.get("input_annualized", True)
        annualize_output = params.get("annualize_output", True)
        day_count = params.get("day_count", 365)

        if len(data) < 2:
            raise ValueError("compound_rates requires at least 2 observations to determine periods")

        # Compound all rates together, inferring days from date gaps
        compounded = Decimal(1)
        total_days = 0

        for i in range(len(data) - 1):
            annual_rate = Decimal(str(data[i].value)) / 100
            days = (data[i + 1].date - data[i].date).days

            if days <= 0:
                raise ValueError("Observations must be in chronological order with positive day gaps")

            if input_annualized:
                # Convert annualized rate to period rate: (1 + r)^(days/365) - 1
                period_rate = (1 + annual_rate) ** (Decimal(days) / day_count) - 1
            else:
                period_rate = annual_rate

            compounded *= (1 + period_rate)
            total_days += days

        # Final result is compounded - 1
        compounded_rate = (compounded - 1) * 100

        if annualize_output and total_days > 0:
            # Annualize: (1 + r)^(365/total_days) - 1
            result_rate = ((compounded) ** (Decimal(day_count) / total_days) - 1) * 100
        else:
            result_rate = compounded_rate

        result_obs = Observation(date=data[-1].date, value=float(result_rate))

        return ComputationResult(
            latest=result_obs,
            summary={
                "compounded_rate": float(compounded_rate),
                "annualized_rate": float(result_rate) if annualize_output else None,
                "total_days": total_days,
                "periods": len(data) - 1,
            },
            metadata={
                "computation": "compound_rates",
                "input_annualized": input_annualized,
                "output_annualized": annualize_output,
                "day_count_convention": day_count,
            },
        )


@registry.register
class ContinuousToDiscrete(Computation):
    """Convert continuously compounded rate to discretely compounded."""

    name = "continuous_to_discrete"
    description = "Convert continuously compounded rate to discretely compounded equivalent"
    params = {
        "periods": ParamSpec(
            type="int",
            description="Compounding frequency per year (1=annual, 2=semi, 4=quarterly, 12=monthly)",
            default=1,
            min_value=1,
        ),
    }
    precision_type = PrecisionType.RATE

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        import math

        periods = params.get("periods", 1)
        results = []

        for obs in data:
            continuous_rate = obs.value / 100
            # r_discrete = n * (e^(r_continuous/n) - 1)
            discrete = periods * (math.exp(continuous_rate / periods) - 1) * 100

            results.append(Observation(date=obs.date, value=discrete))

        return ComputationResult(
            series=results if output == OutputMode.FULL else None,
            latest=results[-1] if results else None,
            metadata={
                "computation": "continuous_to_discrete",
                "compounding_frequency": periods,
            },
        )
