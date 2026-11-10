"""Tests for CausalGraph."""

from __future__ import annotations

from sophia_episto.causal.edge import CausalEdge, expert_priors
from sophia_episto.causal.graph import CausalGraph


def test_update_posteriors_does_not_change_probability_without_evidence():
    graph = CausalGraph()
    graph.add_edge(
        CausalEdge(
            source="a", target="b", probability=0.7, strength=0.0, confidence=0.8
        )
    )
    graph.update_posteriors()
    edge = graph.get_edge("a", "b")
    assert edge is not None
    assert edge.probability == 0.7


def test_expert_prior_survives_empty_batch_updates():
    graph = CausalGraph()
    for edge in expert_priors():
        graph.add_edge(edge)
    before = {
        (edge.source, edge.target): edge.probability for edge in graph.edges
    }
    graph.update_posteriors()
    after = {
        (edge.source, edge.target): edge.probability for edge in graph.edges
    }
    assert before == after
