"""Tests for compounding computations."""

import math
from datetime import date

from sophia_arithmos.core.types import Observation, OutputMode
from sophia_arithmos.computations.compounding import (
    AnnualizeMoM,
    AnnualizeQoQ,
    CompoundDailyRate,
    Deannualize,
)


def test_annualize_mom_compound() -> None:
    """Test MoM to annual with compounding."""
    comp = AnnualizeMoM()
    data = [Observation(date=date(2024, 1, 1), value=0.25)]  # 0.25% MoM

    result = comp.execute(data, {"compound": True}, OutputMode.LATEST)

    # (1 + 0.0025)^12 - 1 ≈ 3.04%
    assert result.latest is not None
    assert 3.0 < result.latest.value < 3.1


def test_annualize_mom_simple() -> None:
    """Test MoM to annual with simple multiplication."""
    comp = AnnualizeMoM()
    data = [Observation(date=date(2024, 1, 1), value=0.25)]  # 0.25% MoM

    result = comp.execute(data, {"compound": False}, OutputMode.LATEST)

    # 0.25 * 12 = 3.0%
    assert result.latest is not None
    assert result.latest.value == 3.0


def test_annualize_qoq() -> None:
    """Test QoQ to annual."""
    comp = AnnualizeQoQ()
    data = [Observation(date=date(2024, 1, 1), value=0.75)]  # 0.75% QoQ

    result = comp.execute(data, {"compound": True}, OutputMode.LATEST)

    # (1 + 0.0075)^4 - 1 ≈ 3.03%
    assert result.latest is not None
    assert 3.0 < result.latest.value < 3.1


def test_compound_daily_rate() -> None:
    """Test daily rate compounding."""
    comp = CompoundDailyRate()
    # 5% annual rate expressed as daily
    data = [Observation(date=date(2024, 1, 1), value=5.0)]

    result = comp.execute(data, {"days": 365, "day_count": 365}, OutputMode.LATEST)

    # (1 + 0.05/365)^365 - 1 ≈ 5.127%
    assert result.latest is not None
    assert 5.1 < result.latest.value < 5.2


def test_deannualize_to_monthly() -> None:
    """Test deannualizing to monthly rate."""
    comp = Deannualize()
    data = [Observation(date=date(2024, 1, 1), value=12.0)]  # 12% annual

    result = comp.execute(data, {"periods": 12, "compound": True}, OutputMode.LATEST)

    # (1 + 0.12)^(1/12) - 1 ≈ 0.949%
    assert result.latest is not None
    assert 0.9 < result.latest.value < 1.0


def test_deannualize_simple() -> None:
    """Test simple deannualization."""
    comp = Deannualize()
    data = [Observation(date=date(2024, 1, 1), value=12.0)]  # 12% annual

    result = comp.execute(data, {"periods": 12, "compound": False}, OutputMode.LATEST)

    # 12 / 12 = 1.0%
    assert result.latest is not None
    assert result.latest.value == 1.0
