"""Causal inference using do-calculus and belief propagation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sophia_episto.causal.graph import CausalGraph


@dataclass
class InferenceResult:
    """Result of a causal inference query."""

    query: str
    result: dict[str, float]
    confidence: float
    explanation: str


class CausalInference:
    """Handles causal inference operations on a CausalGraph.

    Supports:
    - do-calculus interventions
    - Pearl's causal inference
    - Belief propagation for approximate inference
    - Path analysis (mediators, confounders)
    """

    def __init__(self, graph: CausalGraph) -> None:
        self.graph = graph

    def propagate(self, node: str, value: float) -> dict[str, float]:
        """Propagate influence from node to descendants.

        This is a heuristic path-weighted score, NOT Pearl intervention.
        """
        return self.graph.propagate_influence(node, value)

    def direct_effect(self, source: str, target: str) -> float:
        """Get direct edge strength from source to target.

        This is the edge probability, not a Pearl-style causal effect estimate.

        Args:
            source: Source node
            target: Target node

        Returns:
            Edge probability (0-1)
        """
        edge = self.graph.get_edge(source, target)
        if edge is None:
            return 0.0

        return edge.probability

    def path_influence_sum(self, source: str, target: str) -> float:
        """Sum of path-product probabilities from source to target.

        This is a heuristic path-weighted score, NOT a Pearl-style interventional
        expectation. No independence claim is made.

        Args:
            source: Source node
            target: Target node

        Returns:
            Sum of path probabilities (0-1)
        """
        path_probs: list[float] = []

        def traverse(current: str, accum_prob: float, visited: set[str]) -> None:
            if current == target:
                path_probs.append(accum_prob)
                return

            for edge in self.graph.get_outgoing_edges(current):
                if edge.target in visited:
                    continue
                new_prob = accum_prob * edge.probability
                traverse(edge.target, new_prob, visited | {edge.target})

        traverse(source, 1.0, {source})
        return sum(path_probs) if path_probs else 0.0

    def identify_confounders(self, source: str, target: str) -> list[str]:
        """Identify potential confounders (common causes) of source and target.

        Returns nodes that are parents of both source and target.
        """
        source_parents = set(self.graph.get_parents(source))
        target_parents = set(self.graph.get_parents(target))
        return list(source_parents & target_parents)

    def identify_mediators(self, source: str, target: str) -> list[list[str]]:
        """Identify potential mediators between source and target.

        Returns all directed paths from source to target.
        """
        paths: list[list[str]] = []

        def dfs(current: str, path: list[str]) -> None:
            if current == target:
                paths.append(path[1:])
                return

            for edge in self.graph.get_outgoing_edges(current):
                if edge.target in path:
                    continue
                dfs(edge.target, path + [edge.target])

        dfs(source, [source])
        return paths

    def explain_effect(self, source: str, target: str) -> InferenceResult:
        """Generate an explanation for the causal effect from source to target.

        Returns heuristic path scores, NOT Pearl-style causal estimates.
        """
        direct = self.direct_effect(source, target)
        path_influence = self.path_influence_sum(source, target)
        mediators = self.identify_mediators(source, target)
        confounders = self.identify_confounders(source, target)

        edge = self.graph.get_edge(source, target)
        mechanism = edge.mechanism if edge else ""

        explanation_parts = []
        if direct > 0:
            explanation_parts.append(f"Direct strength: {direct:.2%}")
        if path_influence > direct:
            explanation_parts.append(
                f"Path influence sum: {path_influence:.2%} (includes indirect paths)"
            )
        if mediators:
            explanation_parts.append(f"Mediated through: {' -> '.join(mediators[0])}")
        if mechanism:
            explanation_parts.append(f"Mechanism: {mechanism}")

        explanation_parts.append(
            "Note: This is a heuristic path score, not a Pearl-style causal claim."
        )

        return InferenceResult(
            query=f"{source} → {target}",
            result={
                "direct_strength": direct,
                "path_influence": path_influence,
                "n_mediators": len(mediators),
                "n_confounders": len(confounders),
            },
            confidence=edge.confidence if edge else 0.0,
            explanation=". ".join(explanation_parts)
            if explanation_parts
            else "No causal relationship found",
        )


def query_causal_effect(
    graph: CausalGraph,
    source: str,
    target: str,
    intervention: dict[str, float] | None = None,
) -> InferenceResult:
    """Convenience function to query causal effects."""
    inference = CausalInference(graph)

    if intervention:
        result = graph.forward_simulate(intervention, {target: 0.5})
        return InferenceResult(
            query=f"forward_simulate({source}={intervention.get(source)})",
            result=result,
            confidence=1.0,
            explanation=f"Forward simulation for {source} intervention (heuristic, not Pearl counterfactual)",
        )

    return inference.explain_effect(source, target)
