"""Causal graph implementation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sophia_episto.causal.edge import CausalEdge, expert_priors


class CausalGraph:
    """Probabilistic causal graph with Bayesian inference.

    Manages nodes, causal edges, and posterior distributions.
    Supports belief propagation and do-calculus operations.
    """

    def __init__(
        self,
        nodes: set[str] | None = None,
        edges: list[CausalEdge] | None = None,
    ) -> None:
        self.nodes: set[str] = nodes or set()
        self.edges: list[CausalEdge] = edges or []
        self._edge_map: dict[tuple[str, str], CausalEdge] = {}
        self._updated_at: datetime | None = None

        for edge in self.edges:
            self._add_edge_to_map(edge)

    def _add_edge_to_map(self, edge: CausalEdge) -> None:
        """Add edge to internal map for fast lookup."""
        self._edge_map[(edge.source, edge.target)] = edge

    def add_node(self, node_id: str) -> None:
        """Add a node to the graph."""
        self.nodes.add(node_id)

    def add_edge(self, edge: CausalEdge) -> None:
        """Add or update an edge in the graph."""
        self.nodes.add(edge.source)
        self.nodes.add(edge.target)

        key = (edge.source, edge.target)
        if key in self._edge_map:
            existing = self._edge_map[key]
            edge.probability = self._bayesian_update(
                existing.probability,
                edge.strength,
                edge.confidence,
            )
            self.edges = [
                e if (e.source, e.target) != key else edge for e in self.edges
            ]
        else:
            self.edges.append(edge)

        self._edge_map[key] = edge
        self._updated_at = datetime.now(UTC)

    def remove_edge(self, source: str, target: str) -> bool:
        """Remove an edge from the graph."""
        key = (source, target)
        if key in self._edge_map:
            self.edges = [e for e in self.edges if (e.source, e.target) != key]
            del self._edge_map[key]
            self._updated_at = datetime.now(UTC)
            return True
        return False

    def get_edge(self, source: str, target: str) -> CausalEdge | None:
        """Get an edge by source and target."""
        return self._edge_map.get((source, target))

    def get_outgoing_edges(self, node_id: str) -> list[CausalEdge]:
        """Get all edges emanating from a node."""
        return [e for e in self.edges if e.source == node_id]

    def get_incoming_edges(self, node_id: str) -> list[CausalEdge]:
        """Get all edges entering a node."""
        return [e for e in self.edges if e.target == node_id]

    def get_parents(self, node_id: str) -> list[str]:
        """Get parent nodes (causes) of a node."""
        return list({e.source for e in self.edges if e.target == node_id})

    def get_children(self, node_id: str) -> list[str]:
        """Get child nodes (effects) of a node."""
        return list({e.target for e in self.edges if e.source == node_id})

    def _bayesian_update(
        self,
        prior: float,
        likelihood: float,
        confidence: float,
    ) -> float:
        """Update prior probability with likelihood using weighted averaging.

        This is a simplified Bayesian update that combines expert prior
        confidence with empirical likelihood.
        """
        if confidence <= 0:
            return likelihood
        if confidence >= 1:
            return prior

        weight = confidence
        return weight * prior + (1 - weight) * likelihood

    def update_posteriors(self) -> None:
        """Update all edge posteriors using Bayesian inference."""
        for edge in self.edges:
            edge.probability = self._bayesian_update(
                edge.probability,
                edge.strength,
                edge.confidence,
            )
        self._updated_at = datetime.now(UTC)

    def do_calculus(self, node: str, value: float) -> dict[str, float]:
        """Perform do-calculus intervention: do(node = value).

        Returns the estimated effects on downstream nodes.
        """
        effects: dict[str, float] = {node: value}
        visited: set[str] = {node}

        queue = [node]
        while queue:
            current = queue.pop(0)
            for edge in self.get_outgoing_edges(current):
                if edge.target in visited:
                    continue
                visited.add(edge.target)

                parent_effect = effects.get(current, 0.5)
                effect = parent_effect * edge.probability
                effects[edge.target] = effect
                queue.append(edge.target)

        return effects

    def counterfactual(
        self,
        intervention: dict[str, float],
        observation: dict[str, float],
    ) -> dict[str, float]:
        """Compute counterfactual: what would happen if intervention occurred.

        Args:
            intervention: Nodes to intervene on (do(node) = value)
            observation: Current observed values

        Returns:
            Estimated counterfactual values
        """
        result = observation.copy()
        result.update(intervention)

        for node, value in intervention.items():
            effects = self.do_calculus(node, value)
            for affected_node, affected_value in effects.items():
                if affected_node in intervention:
                    continue
                result[affected_node] = affected_value

        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph to dictionary."""
        return {
            "nodes": sorted(list(self.nodes)),
            "edges": [edge.to_dict() for edge in self.edges],
            "updated_at": self._updated_at.isoformat() if self._updated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalGraph:
        """Deserialize graph from dictionary."""
        nodes = set(data.get("nodes", []))
        edges = [CausalEdge.from_dict(e) for e in data.get("edges", [])]
        graph = cls(nodes=nodes, edges=edges)
        if data.get("updated_at"):
            graph._updated_at = datetime.fromisoformat(data["updated_at"])
        return graph


def create_initial_graph() -> CausalGraph:
    """Create the initial causal graph with core concepts and expert priors."""
    from sophia_episto.world_model.concepts import core_concepts

    graph = CausalGraph()

    for concept in core_concepts():
        graph.add_node(concept.concept_id)

    graph.add_node("fed")
    graph.add_node("ecb")
    graph.add_node("boj")

    for edge in expert_priors():
        graph.add_edge(edge)

    return graph


def save_graph(graph: CausalGraph, path: Path | None = None) -> Path:
    """Save graph to JSON file.

    Args:
        graph: The causal graph to save
        path: Optional custom path, defaults to data/causal_graph/graph.json

    Returns:
        Path where the graph was saved
    """
    if path is None:
        path = (
            Path(__file__).resolve().parents[5] / "data" / "causal_graph" / "graph.json"
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump(graph.to_dict(), f, indent=2)

    return path


def load_graph(path: Path | None = None) -> CausalGraph | None:
    """Load graph from JSON file.

    Args:
        path: Optional custom path, defaults to data/causal_graph/graph.json

    Returns:
        Loaded graph or None if file doesn't exist
    """
    if path is None:
        path = (
            Path(__file__).resolve().parents[5] / "data" / "causal_graph" / "graph.json"
        )

    if not path.exists():
        return None

    with open(path) as f:
        data = json.load(f)

    return CausalGraph.from_dict(data)
