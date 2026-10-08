"""Tests for stationarity preprocessing."""

from __future__ import annotations

import numpy as np
import pytest

from sophia_episto.causal.preprocessing import (
    StationarityReport,
    is_stationary,
    prepare_for_discovery,
)


def test_is_stationary_detects_white_noise():
    rng = np.random.default_rng(0)
    y = rng.standard_normal(200).tolist()
    report = is_stationary(y)
    assert report.stationary is True
    assert report.p_value < 0.05


def test_is_stationary_flags_random_walk():
    rng = np.random.default_rng(0)
    y = np.cumsum(rng.standard_normal(200)).tolist()
    report = is_stationary(y)
    assert report.stationary is False


def test_prepare_for_discovery_differences_nonstationary_series():
    rng = np.random.default_rng(0)
    stationary = rng.standard_normal(200).tolist()
    walk = np.cumsum(rng.standard_normal(200)).tolist()
    data = {"stationary": stationary, "walk": walk}

    prepared, report = prepare_for_discovery(data)
    # Walk gets differenced (200 -> 199), then both trimmed to common length 199
    assert len(prepared["walk"]) == 199
    assert len(prepared["stationary"]) == 199
    assert "walk" in report.differenced
    assert "stationary" not in report.differenced


def test_prepare_for_discovery_aligns_lengths():
    """All returned series must share the same length for discovery."""
    rng = np.random.default_rng(0)
    data = {
        "a": rng.standard_normal(200).tolist(),
        "b": np.cumsum(rng.standard_normal(200)).tolist(),
    }
    prepared, _ = prepare_for_discovery(data)
    lengths = {len(v) for v in prepared.values()}
    assert len(lengths) == 1, f"lengths diverged: {lengths}"


def test_prepare_for_discovery_double_differences_when_needed():
    rng = np.random.default_rng(0)
    base = np.cumsum(np.cumsum(rng.standard_normal(250)))
    prepared, report = prepare_for_discovery({"x": base.tolist()}, max_diff=2)
    rep = is_stationary(prepared["x"])
    assert rep.stationary is True
    assert report.diff_orders["x"] >= 1
