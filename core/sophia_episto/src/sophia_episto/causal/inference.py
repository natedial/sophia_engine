"""Heuristic causal inference (NOT Pearl-style do-calculus)."""

from __future__ import annotations

from dataclasses import dataclass

from sophia_episto.causal.graph import CausalGraph


@dataclass
class InferenceResult:
    """Result of a heuristic causal query."""

    query: str
    result: dict[str, float]
    confidence: float
    explanation: str


class CausalInference:
    """Heuristic path-analysis over a CausalGraph.

    This class does NOT implement do-calculus, backdoor adjustment, or
    Pearl-style counterfactuals. It provides:

    - Direct edge strength lookup (`direct_strength`)
    - Path-product influence sums (`path_influence`)
    - Structural enumeration of mediators and shared parents

    For Pearl-style refutation on flagship edges, see
    `sophia_episto.causal.evaluation`.
    """

    def __init__(self, graph: CausalGraph) -> None:
        self.graph = graph

    def direct_strength(
        self,
        source: str,
        target: str,
        control: list[str] | None = None,
    ) -> float:
        """Return the direct edge probability from source to target.

        If `control` is provided, down-weights by the probability of each
        control node's edge into target. This is a heuristic adjustment,
        not Pearl-style backdoor correction.
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

    def path_influence(self, source: str, target: str) -> float:
        """Sum of path-products across all directed source→target paths.

        Each path contributes the product of edge probabilities along it.
        Parallel paths are summed without attempting to correct for the
        overlap — this is heuristic influence, not identified causal effect.
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

    def identify_shared_parents(self, source: str, target: str) -> list[str]:
        """Return nodes that are direct parents of both source and target.

        These are structural common-cause candidates. Calling them
        "confounders" would imply a Pearl identification claim this
        module does not make.
        """
        source_parents = set(self.graph.get_parents(source))
        target_parents = set(self.graph.get_parents(target))
        return list(source_parents & target_parents)

    def identify_mediators(self, source: str, target: str) -> list[list[str]]:
        """Return every directed path from source to target (excluding source)."""
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
        """Build a heuristic explanation of source→target influence."""
        direct = self.direct_strength(source, target)
        total = self.path_influence(source, target)
        mediators = self.identify_mediators(source, target)
        shared_parents = self.identify_shared_parents(source, target)

        edge = self.graph.get_edge(source, target)
        mechanism = edge.mechanism if edge else ""

        explanation_parts = []
        if direct > 0:
            explanation_parts.append(f"Direct strength: {direct:.2%}")
        if total > direct:
            explanation_parts.append(
                f"Path influence: {total:.2%} (includes indirect paths)"
            )
        if mediators:
            explanation_parts.append(f"Mediated through: {' -> '.join(mediators[0])}")
        if mechanism:
            explanation_parts.append(f"Mechanism: {mechanism}")

        return InferenceResult(
            query=f"{source} → {target}",
            result={
                "direct_strength": direct,
                "path_influence": total,
                "n_mediators": len(mediators),
                "n_shared_parents": len(shared_parents),
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
    """Query heuristic influence between two nodes.

    If `intervention` is provided, runs `forward_propagate` (NOT Pearl
    do-calculus) and returns the propagated value at `target`.
    """
    inference = CausalInference(graph)

    if intervention:
        propagated = graph.forward_propagate(intervention, {target: 0.5})
        target_value = propagated.get(target, 0.0)
        return InferenceResult(
            query=f"forward_propagate({source}={intervention.get(source)})",
            result={target: target_value},
            confidence=0.0,
            explanation=(
                f"Heuristic forward propagation from {source}. "
                "Not a Pearl counterfactual — no abduction/action/prediction."
            ),
        )

    return inference.explain_effect(source, target)
