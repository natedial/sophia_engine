"""Tests for effect-size estimators."""
from __future__ import annotations

import numpy as np
import pytest

from sophia_episto.causal.effect_size import (
    partial_r_squared,
    standardized_beta,
    strength_from_lagged_regression,
)


def test_standardized_beta_near_one_for_perfect_linear_relationship():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(200)
    y = 2.0 * x  # perfect
    beta = standardized_beta(x, y)
    assert pytest.approx(abs(beta), abs=0.02) == 1.0


def test_standardized_beta_near_zero_for_independent_series():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(500)
    y = rng.standard_normal(500)
    beta = standardized_beta(x, y)
    assert abs(beta) < 0.15


def test_partial_r_squared_bounded_0_1():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(200)
    y = 0.5 * x + 0.5 * rng.standard_normal(200)
    r2 = partial_r_squared(x, y)
    assert 0.0 <= r2 <= 1.0


def test_strength_from_lagged_regression_increases_with_dependence():
    """Stronger lag-1 dependence should produce larger strength."""
    rng = np.random.default_rng(0)
    n = 300
    noise = rng.standard_normal(n)

    x = rng.standard_normal(n)
    y_strong = np.zeros(n)
    y_weak = np.zeros(n)
    for t in range(1, n):
        y_strong[t] = 0.8 * x[t - 1] + 0.2 * noise[t]
        y_weak[t] = 0.1 * x[t - 1] + 0.9 * noise[t]

    s_strong = strength_from_lagged_regression(x.tolist(), y_strong.tolist(), lag=1)
    s_weak = strength_from_lagged_regression(x.tolist(), y_weak.tolist(), lag=1)
    assert s_strong > s_weak
    assert 0.0 <= s_weak <= 1.0
    assert 0.0 <= s_strong <= 1.0
