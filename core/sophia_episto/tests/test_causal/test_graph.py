"""Tests for CausalGraph."""

from __future__ import annotations

from sophia_episto.causal.edge import CausalEdge
from sophia_episto.causal.graph import CausalGraph


def test_update_posteriors_does_not_raise():
    g = CausalGraph()
    g.add_edge(
        CausalEdge(
            source="a", target="b", probability=0.5, strength=0.3, confidence=0.7
        )
    )
    g.update_posteriors()
    edge = g.get_edge("a", "b")
    assert edge is not None
    assert 0.0 <= edge.probability <= 1.0
