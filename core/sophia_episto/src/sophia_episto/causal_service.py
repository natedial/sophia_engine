"""Causal world model service for scheduled execution and Sophia Prima integration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sophia_episto.causal import (
    CausalGraph,
    CausalInference,
    create_initial_graph,
    load_graph,
    query_causal_effect,
    save_graph,
)
from sophia_episto.hypothesis import HypothesisGenerator, HypothesisStatus

logger = logging.getLogger("sophia_episto.causal_service")


class CausalWorldModelService:
    """Service for managing the causal world model.

    Provides:
    - Scheduled batch execution (daily at 5 PM ET)
    - Integration point for Sophia Prima causal queries
    - Hypothesis generation and testing
    """

    def __init__(
        self,
        graph: CausalGraph | None = None,
        hypothesis_generator: HypothesisGenerator | None = None,
    ) -> None:
        self.graph = graph
        self.hypothesis_generator = hypothesis_generator or HypothesisGenerator()
        self._data: dict[str, list[float]] = {}

    def initialize(self) -> None:
        """Initialize the causal graph, loading from persistence or creating new."""
        if self.graph is None:
            self.graph = load_graph()
        if self.graph is None:
            logger.info("Creating new causal graph with expert priors")
            self.graph = create_initial_graph()
            save_graph(self.graph)

    def ingest_data(self, series_id: str, values: list[float]) -> None:
        """Ingest time series data for causal discovery."""
        self._data[series_id] = values

    def run_daily_batch(self) -> dict[str, Any]:
        """Run the daily scheduled batch:

        1. Ingest new data from Scrivener
        2. Run causal discovery (Granger causality)
        3. Update Bayesian posteriors
        4. Generate new hypotheses
        5. Trigger Oikonomia model runs for testing
        6. Push results to dashboard + Sophia Prima context
        """
        if self.graph is None:
            self.initialize()

        results: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "edges_updated": 0,
            "hypotheses_generated": 0,
            "model_runs_triggered": 0,
        }

        variables = list(self._data.keys())
        logger.info(f"Running causal discovery on {len(variables)} variables")

        if len(variables) >= 2:
            from sophia_episto.causal.discovery import CausalDiscovery

            discovery = CausalDiscovery(self._data)
            discovered = discovery.discover_granger(variables, max_lag=5, alpha=0.05)

            for edge in discovered:
                existing = self.graph.get_edge(edge.source, edge.target)
                if existing:
                    existing.strength = edge.strength
                    existing.p_value = edge.p_value
                    results["edges_updated"] += 1
                else:
                    from sophia_episto.causal.edge import CausalEdge

                    new_edge = CausalEdge(
                        source=edge.source,
                        target=edge.target,
                        probability=edge.strength,
                        strength=edge.strength,
                        confidence=0.5,
                        mechanism=f"Discovered via Granger causality (p={edge.p_value:.3f})",
                    )
                    self.graph.add_edge(new_edge)
                    results["edges_updated"] += 1

                    hypothesis = (
                        self.hypothesis_generator.generate_from_discovered_edge(
                            edge_id=f"{edge.source}-{edge.target}",
                            source=edge.source,
                            target=edge.target,
                            strength=edge.strength,
                            mechanism=new_edge.mechanism,
                        )
                    )
                    results["hypotheses_generated"] += 1

        self.graph.update_posteriors()
        save_graph(self.graph)

        testing_hypotheses = self.hypothesis_generator.get_hypotheses_by_status(
            HypothesisStatus.PROPOSED
        )
        results["pending_hypotheses"] = len(testing_hypotheses)

        logger.info(f"Daily batch complete: {results}")
        return results

    def query(self, source: str, target: str) -> dict[str, Any]:
        """Query causal effect from source to target."""
        if self.graph is None:
            self.initialize()

        inference = CausalInference(self.graph)
        result = inference.explain_effect(source, target)

        return {
            "source": source,
            "target": target,
            "direct_effect": result.result.get("direct_effect", 0),
            "total_effect": result.result.get("total_effect", 0),
            "confidence": result.confidence,
            "explanation": result.explanation,
            "n_mediators": result.result.get("n_mediators", 0),
            "n_confounders": result.result.get("n_confounders", 0),
        }

    def explain(self, node: str) -> dict[str, Any]:
        """Explain a node's causal relationships."""
        if self.graph is None:
            self.initialize()

        parents = self.graph.get_parents(node)
        children = self.graph.get_children(node)

        incoming_edges = self.graph.get_incoming_edges(node)
        outgoing_edges = self.graph.get_outgoing_edges(node)

        return {
            "node": node,
            "causes": parents,
            "effects": children,
            "incoming_confidence": [e.confidence for e in incoming_edges],
            "outgoing_strength": [e.strength for e in outgoing_edges],
        }

    def get_graph_state(self) -> dict[str, Any]:
        """Get current graph state for dashboard."""
        if self.graph is None:
            self.initialize()

        return {
            "nodes": sorted(list(self.graph.nodes)),
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "probability": e.probability,
                    "confidence": e.confidence,
                    "strength": e.strength,
                    "mechanism": e.mechanism,
                }
                for e in self.graph.edges
            ],
            "node_count": len(self.graph.nodes),
            "edge_count": len(self.graph.edges),
            "updated_at": self.graph._updated_at.isoformat()
            if self.graph._updated_at
            else None,
        }

    def list_hypotheses(
        self, status: HypothesisStatus | None = None
    ) -> list[dict[str, Any]]:
        """List hypotheses, optionally filtered by status."""
        if status:
            hypotheses = self.hypothesis_generator.get_hypotheses_by_status(status)
        else:
            hypotheses = self.hypothesis_generator.list_hypotheses()

        return [h.to_dict() for h in hypotheses]


_service_instance: CausalWorldModelService | None = None


def get_causal_service() -> CausalWorldModelService:
    """Get the global causal service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = CausalWorldModelService()
        _service_instance.initialize()
    return _service_instance
