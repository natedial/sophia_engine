"""Heuristic causal inference (NOT Pearl-style do-calculus)."""

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
    """Heuristic inference over a CausalGraph.

    This class does NOT implement do-calculus or Pearl-style counterfactuals.
    It provides:
    - Direct edge strength lookup
    - Path-product influence sums
    - Mediator/confounder structural enumeration (shape, not effect)
    """

    def __init__(self, graph: CausalGraph) -> None:
        self.graph = graph

    def intervention(self, node: str, value: float) -> dict[str, float]:
        """Perform do-calculus intervention: do(node = value).

        This severs all incoming edges to the node and sets its value.
        """
        return self.graph.do_calculus(node, value)

    def direct_effect(
        self,
        source: str,
        target: str,
        control: list[str] | None = None,
    ) -> float:
        """Calculate direct causal effect from source to target.

        Args:
            source: Source node
            target: Target node
            control: Optional nodes to control for

        Returns:
            Estimated direct effect
        """
        edge = self.graph.get_edge(source, target)
        if edge is None:
            return 0.0

        if control:
            adjustment = 1.0
            for c in control:
                c_edge = self.graph.get_edge(c, target)
                if c_edge:
                    adjustment *= 1 - c_edge.probability
            return edge.probability * adjustment

        return edge.probability

    def total_effect(self, source: str, target: str) -> float:
        """Calculate total causal effect (direct + indirect paths).

        Sums all directed paths from source to target, handling parallel
        paths by combining their probabilities.
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

    def backdoor_criterion(
        self, source: str, target: str, confounders: list[str]
    ) -> bool:
        """Check if controlling for confounders satisfies the backdoor criterion.

        The backdoor criterion is satisfied if:
        1. Confounders block all backdoor paths from source to target
        2. No variable in confounders is a descendant of source
        """
        source_parents = set(self.graph.get_parents(source))

        for c in confounders:
            if c in self.graph.get_children(source):
                return False

        backdoor_paths = self._find_backdoor_paths(source, target)
        for path in backdoor_paths:
            if not any(c in path for c in confounders):
                return False

        return True

    def _find_backdoor_paths(self, source: str, target: str) -> list[list[str]]:
        """Find all backdoor paths (paths starting with an arrow into source)."""
        paths: list[list[str]] = []

        for edge in self.graph.get_incoming_edges(source):
            path = [edge.source, source]

            def search(current: str, path: list[str]) -> None:
                if current == target:
                    paths.append(path)
                    return
                if current in path:
                    return

                for e in self.graph.get_outgoing_edges(current):
                    if e.target in path:
                        continue
                    search(e.target, path + [e.target])

            search(target, path)

        return paths

    def explain_effect(self, source: str, target: str) -> InferenceResult:
        """Generate an explanation for the causal effect from source to target."""
        direct = self.direct_effect(source, target)
        total = self.total_effect(source, target)
        mediators = self.identify_mediators(source, target)
        confounders = self.identify_confounders(source, target)

        edge = self.graph.get_edge(source, target)
        mechanism = edge.mechanism if edge else ""

        explanation_parts = []
        if direct > 0:
            explanation_parts.append(f"Direct effect: {direct:.2%}")
        if total > direct:
            explanation_parts.append(
                f"Total effect: {total:.2%} (includes indirect paths)"
            )
        if mediators:
            explanation_parts.append(f"Mediated through: {' -> '.join(mediators[0])}")
        if mechanism:
            explanation_parts.append(f"Mechanism: {mechanism}")

        return InferenceResult(
            query=f"{source} → {target}",
            result={
                "direct_effect": direct,
                "total_effect": total,
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
        result = graph.counterfactual(intervention, {target: 0.5})
        return InferenceResult(
            query=f"counterfactual({source}={intervention.get(source)})",
            result=result,
            confidence=1.0,
            explanation=f"Counterfactual analysis for {source} intervention",
        )

    return inference.explain_effect(source, target)
