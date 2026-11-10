from __future__ import annotations

import pytest

from sophia_episto.causal.edge import CausalEdge, expert_priors
from sophia_episto.causal.graph import CausalGraph
from sophia_episto.hypothesis.generator import Hypothesis, HypothesisStatus


def test_empty_update_does_not_decay_expert_prior():
    prior = next(
        edge
        for edge in expert_priors()
        if edge.source == "inflation" and edge.target == "policy"
    )
    graph = CausalGraph()
    graph.add_edge(prior)
    assert graph.get_edge("inflation", "policy").probability == 0.7

    graph.update_posteriors()
    graph.update_posteriors()
    assert graph.get_edge("inflation", "policy").probability == 0.7


def test_add_edge_without_new_evidence_does_not_blend():
    graph = CausalGraph()
    graph.add_edge(
        CausalEdge(source="a", target="b", probability=0.7, confidence=0.8, strength=0.0)
    )
    graph.add_edge(
        CausalEdge(source="a", target="b", probability=0.1, confidence=0.8, strength=0.0)
    )
    assert graph.get_edge("a", "b").probability == 0.7


def test_mark_validated_empty_evidence_is_rejected():
    hypothesis = Hypothesis(
        id="h1",
        description="x causes y",
        source="x",
        target="y",
        mechanism="channel",
    )
    with pytest.raises(RuntimeError, match="propose_assessment"):
        hypothesis.mark_validated({})
    assert hypothesis.status == HypothesisStatus.PROPOSED
    assert hypothesis.confidence == 0.0


def test_mark_validated_never_sets_certainty():
    hypothesis = Hypothesis(
        id="h1",
        description="x causes y",
        source="x",
        target="y",
        mechanism="channel",
    )
    with pytest.raises(RuntimeError):
        hypothesis.mark_validated({"note": "looks convincing"})
    assert hypothesis.confidence == 0.0
    assert hypothesis.status != HypothesisStatus.VALIDATED
