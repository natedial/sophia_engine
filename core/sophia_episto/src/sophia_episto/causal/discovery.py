"""Causal discovery from data using Granger causality and PC algorithm."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger("sophia_episto.causal.discovery")


@dataclass
class DiscoveredEdge:
    """A candidate causal edge discovered from data."""

    source: str
    target: str
    statistic: float
    p_value: float
    strength: float
    method: str
    lag: int


class CausalDiscovery:
    """Methods for discovering causal relationships from time series data.

    Supports:
    - Granger causality testing
    - PC algorithm (via causal-learn)
    - Regime-aware detection
    """

    def __init__(self, data: dict[str, list[float]] | None = None) -> None:
        self.data = data or {}

    def add_series(self, name: str, values: list[float]) -> None:
        """Add a time series to the dataset."""
        self.data[name] = values

    def granger_test(
        self,
        source: str,
        target: str,
        max_lag: int = 5,
        alpha: float = 0.05,
    ) -> DiscoveredEdge | None:
        """Test for Granger causality from source to target.

        Returns a DiscoveredEdge if Granger causality is detected, None otherwise.
        Uses Arithmos GrangerCausality computation.
        """
        if source not in self.data or target not in self.data:
            return None

        target_values = self.data[target]
        source_values = self.data[source]

        if len(target_values) <= max_lag + 1:
            return None

        try:
            import json
            from datetime import datetime, timedelta

            from sophia_arithmos.computations.causality import GrangerCausality
            from sophia_arithmos.core.types import Observation, OutputMode

            observations = [
                Observation(
                    id=str(i),
                    timestamp=datetime(2024, 1, 1) + timedelta(days=i),
                    value=v,
                )
                for i, v in enumerate(target_values)
            ]

            params = {
                "source": source,
                "target": target,
                "source_values": json.dumps(source_values),
                "max_lag": max_lag,
                "alpha": alpha,
            }

            result = GrangerCausality().execute(
                observations, params, OutputMode.SUMMARY
            )
            summary = result.summary

            if summary.get("is_granger_causal"):
                return DiscoveredEdge(
                    source=source,
                    target=target,
                    statistic=summary.get("test_statistic", 0),
                    p_value=summary.get("p_value", 1.0),
                    strength=summary.get("strength", 0),
                    method="granger",
                    lag=summary.get("best_lag", max_lag),
                )

        except (ImportError, ValueError) as exc:
            logger.debug("granger test failed for %s -> %s: %s", source, target, exc)

        return None

    def discover_granger(
        self,
        variables: list[str],
        max_lag: int = 5,
        alpha: float = 0.05,
    ) -> list[DiscoveredEdge]:
        """Run Granger causality discovery across all variable pairs."""
        edges = []

        for i, var1 in enumerate(variables):
            for var2 in variables:
                if var1 == var2:
                    continue

                result = self.granger_test(var1, var2, max_lag, alpha)
                if result:
                    edges.append(result)

        return edges

    def pc_algorithm(
        self,
        variables: list[str],
        alpha: float = 0.05,
    ) -> list[tuple[str, str]]:
        """Run PC algorithm for causal structure learning.

        Returns list of directed edges (source, target).
        Requires causal-learn package.
        """
        try:
            from causallearn.search.ConstraintBased.PC import pc
            from causallearn.utils.cit import fisherz

            if len(variables) < 2:
                return []

            data_matrix = np.column_stack([self.data[v] for v in variables])

            cg = pc(data_matrix, alpha=alpha, indep_test=fisherz)

            edges = []
            graph = cg.G.graph

            for i, var1 in enumerate(variables):
                for j, var2 in enumerate(variables):
                    if i >= j:
                        continue

                    if graph[i, j] == -1 and graph[j, i] == 1:
                        edges.append((var1, var2))
                    elif graph[i, j] == 1 and graph[j, i] == -1:
                        edges.append((var2, var1))

            return edges

        except ImportError:
            return []

    def regime_aware_detection(
        self,
        variables: list[str],
        regimes: dict[str, list[int]],
    ) -> dict[str, list[DiscoveredEdge]]:
        """Run causal discovery within different market regimes.

        Args:
            variables: List of variable names
            regimes: Dict mapping regime name to list of indices

        Returns:
            Dict mapping regime name to discovered edges
        """
        results = {}

        for regime_name, indices in regimes.items():
            regime_data = {
                k: [v[i] for i in indices if i < len(v)] for k, v in self.data.items()
            }

            discovery = CausalDiscovery(regime_data)
            edges = discovery.discover_granger(variables)
            results[regime_name] = edges

        return results


def rank_candidates(
    edges: list[DiscoveredEdge],
    min_strength: float = 0.5,
) -> list[DiscoveredEdge]:
    """Rank discovered edges by strength and filter by minimum threshold."""
    filtered = [e for e in edges if e.strength >= min_strength]
    return sorted(filtered, key=lambda e: e.strength, reverse=True)
