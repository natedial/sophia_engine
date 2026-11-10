"""Tests for CausalInference and graph propagation."""
from __future__ import annotations

import pytest

from sophia_episto.causal.edge import CausalEdge
from sophia_episto.causal.graph import CausalGraph
from sophia_episto.causal.inference import CausalInference


def test_forward_propagate_exists_and_forward_simulate_removed():
    g = CausalGraph()
    g.add_edge(CausalEdge(source="a", target="b", probability=0.5))
    assert hasattr(g, "forward_propagate")
    assert not hasattr(g, "forward_simulate"), "forward_simulate must be renamed"


def test_forward_propagate_merges_intervention_with_observation():
    g = CausalGraph()
    g.add_edge(CausalEdge(source="x", target="y", probability=0.8))
    g.add_edge(CausalEdge(source="y", target="z", probability=0.5))

    result = g.forward_propagate(intervention={"x": 1.0}, observation={"y": 0.1, "z": 0.1})
    assert result["x"] == 1.0  # intervention preserved
    # z propagates via x -> y -> z with probabilities 0.8 * 0.5 = 0.4
    assert pytest.approx(result["z"], rel=1e-6) == 0.4
