"""Tests for joining two dated series (review finding 6)."""

from datetime import date, timedelta

import pytest

from sophia_arithmos.computations.alignment import infer_frequency, inner_join_on_date
from sophia_arithmos.core.types import Observation


def _business_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _month_starts(year: int, count: int) -> list[date]:
    return [date(year + (m // 12), m % 12 + 1, 1) for m in range(count)]


def _series(dates: list[date], offset: float = 0.0) -> list[Observation]:
    return [Observation(date=d, value=float(i) + offset) for i, d in enumerate(dates)]


def test_infer_frequency_daily_with_weekends() -> None:
    assert infer_frequency(_business_days(date(2024, 1, 1), 30)) == "daily"


def test_infer_frequency_monthly() -> None:
    assert infer_frequency(_month_starts(2020, 24)) == "monthly"


def test_infer_frequency_needs_two_dates() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        infer_frequency([date(2024, 1, 1)])


def test_duplicate_dates_rejected() -> None:
    dates = _business_days(date(2024, 1, 1), 20)
    source = _series(dates + [dates[3]])
    with pytest.raises(ValueError, match="duplicate"):
        inner_join_on_date(source, _series(dates))


def test_mixed_frequencies_rejected() -> None:
    daily = _series(_business_days(date(2020, 1, 1), 60))
    monthly = _series(_month_starts(2020, 24))
    with pytest.raises(ValueError) as exc:
        inner_join_on_date(daily, monthly)
    assert "daily" in str(exc.value)
    assert "monthly" in str(exc.value)


def test_join_keeps_only_shared_dates() -> None:
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]
    source = _series(dates[5:], offset=100.0)
    target = _series(dates)

    joined = inner_join_on_date(source, target)

    assert len(joined.dates) == 35
    assert joined.dates[0] == dates[5]
    assert joined.frequency == "daily"
    # Pairs line up by date, not by position.
    assert joined.source[0] == 100.0
    assert joined.target[0] == 5.0


def test_join_ignores_input_order() -> None:
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(30)]
    source = _series(dates)
    joined = inner_join_on_date(list(reversed(source)), _series(dates))
    assert joined.dates == dates
    assert joined.source == [float(i) for i in range(30)]
