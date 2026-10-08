"""Stationarity testing and auto-differencing for causal discovery."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class StationarityReport:
    """Result of an Augmented Dickey-Fuller (ADF) test."""

    stationary: bool
    p_value: float
    test_statistic: float
    lag: int


@dataclass
class PreprocessingReport:
    """Summary of preprocessing decisions for a batch."""

    differenced: list[str] = field(default_factory=list)
    diff_orders: dict[str, int] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)


def is_stationary(values: list[float], alpha: float = 0.05) -> StationarityReport:
    """Run ADF test. Returns StationarityReport.

    Null hypothesis of ADF: unit root (non-stationary). We reject at alpha
    to declare stationarity.
    """
    from statsmodels.tsa.stattools import adfuller

    arr = np.asarray(values, dtype=float)
    if len(arr) < 15:
        return StationarityReport(
            stationary=True, p_value=1.0, test_statistic=0.0, lag=0
        )

    try:
        stat, p_value, lag, *_ = adfuller(arr, autolag="AIC")
    except (ValueError, np.linalg.LinAlgError):
        return StationarityReport(
            stationary=True, p_value=1.0, test_statistic=0.0, lag=0
        )

    return StationarityReport(
        stationary=bool(p_value < alpha),
        p_value=float(p_value),
        test_statistic=float(stat),
        lag=int(lag),
    )


def prepare_for_discovery(
    data: dict[str, list[float]],
    alpha: float = 0.05,
    max_diff: int = 2,
    min_length: int = 30,
) -> tuple[dict[str, list[float]], PreprocessingReport]:
    """Ensure every series is stationary (differencing up to `max_diff` times)
    and align all series to a common length by trimming from the front.

    Returns (prepared_data, report).
    """
    report = PreprocessingReport()
    prepared: dict[str, list[float]] = {}

    for name, values in data.items():
        arr = np.asarray(values, dtype=float)
        order = 0
        while order < max_diff:
            rep = is_stationary(arr.tolist(), alpha=alpha)
            if rep.stationary:
                break
            arr = np.diff(arr)
            order += 1

        if len(arr) < min_length:
            report.dropped.append(name)
            continue

        if order > 0:
            report.differenced.append(name)
        report.diff_orders[name] = order
        prepared[name] = arr.tolist()

    if not prepared:
        return prepared, report

    common = min(len(v) for v in prepared.values())
    prepared = {k: v[-common:] for k, v in prepared.items()}
    return prepared, report
