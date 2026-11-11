"""Align two dated series before a bivariate computation.

Pairs are matched by date, never by list position. Series of different
frequencies are rejected rather than resampled: choosing how to resample is
a modelling decision that belongs to the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

from ..core.types import Observation

# Calendar definitions, as (name, lowest, highest) median gap in days.
# A daily series of business days has gaps of 1 to 3 days, 4 over holidays.
_FREQUENCY_GAPS: tuple[tuple[str, float, float], ...] = (
    ("daily", 1, 4),
    ("weekly", 5, 9),
    ("monthly", 25, 35),
    ("quarterly", 85, 95),
    ("annual", 360, 370),
)


@dataclass(frozen=True)
class JoinedSeries:
    """Two series restricted to their shared dates, in date order."""

    dates: list[date]
    source: list[float]
    target: list[float]
    frequency: str


def infer_frequency(dates: list[date]) -> str:
    """Name a series' frequency from the median gap between its dates."""
    if len(dates) < 2:
        raise ValueError("Cannot infer frequency: need at least 2 dates")
    ordered = sorted(dates)
    gap = median((b - a).days for a, b in zip(ordered, ordered[1:], strict=False))
    for name, low, high in _FREQUENCY_GAPS:
        if low <= gap <= high:
            return name
    raise ValueError(f"Cannot infer frequency: median gap of {gap} days")


def _require_continuous(dates: list[date], frequency: str) -> None:
    """Every step between joined dates must be one period of the frequency.

    A lag is one step in the joined series, so a missing stretch would make
    a lag span several periods without anyone seeing it.
    """
    low, high = next((lo, hi) for name, lo, hi in _FREQUENCY_GAPS if name == frequency)
    for earlier, later in zip(dates, dates[1:], strict=False):
        days = (later - earlier).days
        if not low <= days <= high:
            raise ValueError(
                f"Joined {frequency} series has a gap of {days} days from "
                f"{earlier.isoformat()} to {later.isoformat()}; "
                f"a {frequency} step is {low:g} to {high:g} days"
            )


def _by_date(series: list[Observation], label: str) -> dict[date, float]:
    values: dict[date, float] = {}
    for obs in series:
        if obs.date in values:
            raise ValueError(f"{label} series has duplicate date {obs.date.isoformat()}")
        values[obs.date] = obs.value
    return values


def inner_join_on_date(source: list[Observation], target: list[Observation]) -> JoinedSeries:
    """Keep the dates both series observe; reject duplicates and mixed frequency."""
    source_by_date = _by_date(source, "source")
    target_by_date = _by_date(target, "target")
    source_frequency = infer_frequency(list(source_by_date))
    target_frequency = infer_frequency(list(target_by_date))
    if source_frequency != target_frequency:
        raise ValueError(
            f"Mixed frequencies: source is {source_frequency}, "
            f"target is {target_frequency}"
        )
    shared = sorted(source_by_date.keys() & target_by_date.keys())
    _require_continuous(shared, source_frequency)
    return JoinedSeries(
        dates=shared,
        source=[source_by_date[d] for d in shared],
        target=[target_by_date[d] for d in shared],
        frequency=source_frequency,
    )
