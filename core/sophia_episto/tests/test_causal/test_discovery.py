"""Tests for CausalDiscovery."""
from __future__ import annotations

import numpy as np

from sophia_episto.causal.discovery import CausalDiscovery


def test_granger_test_returns_edge_for_strongly_causal_pair():
    """When x strongly Granger-causes y, we must return a DiscoveredEdge."""
    rng = np.random.default_rng(42)
    n = 200
    x = rng.standard_normal(n)
    # y[t] = 0.8 * x[t-1] + small noise — x strongly causes y.
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = 0.8 * x[t - 1] + 0.1 * rng.standard_normal()

    disc = CausalDiscovery({"x": x.tolist(), "y": y.tolist()})
    edge = disc.granger_test("x", "y", max_lag=3, alpha=0.05)
    assert edge is not None, "Granger test must detect the causal relationship"
    assert edge.source == "x"
    assert edge.target == "y"
    assert 0.0 <= edge.p_value <= 1.0
