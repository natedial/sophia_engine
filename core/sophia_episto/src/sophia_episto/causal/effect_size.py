"""Effect-size estimators for causal edge strength.

Replaces the prior `strength = 1 - p_value` convention, which is not an
effect size. These return quantities in [0,1] with honest interpretations:

- `standardized_beta`: β from OLS of z-scored y on z-scored x. Returns raw β
  (can be negative); call `abs()` if you want a magnitude.
- `partial_r_squared`: squared correlation in [0,1].
- `strength_from_lagged_regression`: partial R² from regressing y[t] on
  x[t-lag] after projecting out y's own AR(lag) dynamics — this is the
  Granger-style "incremental predictive power" expressed as a bounded
  effect-size-like quantity.
"""

from __future__ import annotations

import numpy as np


def _zscore(v: np.ndarray) -> np.ndarray:
    std = v.std(ddof=1)
    if std == 0:
        return np.zeros_like(v)
    return (v - v.mean()) / std


def standardized_beta(x: np.ndarray, y: np.ndarray) -> float:
    """Standardized OLS slope of y on x. In [-1, 1] for normally distributed pairs."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    zx = _zscore(x)
    zy = _zscore(y)
    denom = float(zx @ zx)
    if denom == 0:
        return 0.0
    return float((zx @ zy) / denom)


def partial_r_squared(x: np.ndarray, y: np.ndarray) -> float:
    """Squared Pearson correlation. Always in [0,1]."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    if x.std(ddof=1) == 0 or y.std(ddof=1) == 0:
        return 0.0
    r = float(np.corrcoef(x, y)[0, 1])
    return r * r


def strength_from_lagged_regression(
    source_values: list[float],
    target_values: list[float],
    lag: int = 1,
) -> float:
    """Partial R² of y[t] on x[t-lag] after AR(lag) projection of y.

    Returns a value in [0,1] representing the extra variance of y explained
    by past x beyond what y's own lags already explain. This is the
    Granger-style incremental predictive contribution, framed as an effect
    size rather than `1 - p_value`.
    """
    x = np.asarray(source_values, dtype=float)
    y = np.asarray(target_values, dtype=float)
    if len(x) != len(y) or len(y) <= lag + 5:
        return 0.0

    y_t = y[lag:]
    x_lag = x[:-lag]
    y_lag = y[:-lag]

    Z = np.column_stack([np.ones(len(y_lag)), y_lag])
    try:
        coeffs, *_ = np.linalg.lstsq(Z, y_t, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    resid_y = y_t - Z @ coeffs

    try:
        coeffs_x, *_ = np.linalg.lstsq(Z, x_lag, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    resid_x = x_lag - Z @ coeffs_x

    if resid_x.std(ddof=1) == 0 or resid_y.std(ddof=1) == 0:
        return 0.0

    r = float(np.corrcoef(resid_x, resid_y)[0, 1])
    return max(0.0, min(1.0, r * r))
