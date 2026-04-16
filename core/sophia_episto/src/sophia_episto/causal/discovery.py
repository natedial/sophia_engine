"""Causal discovery from data using Granger causality and PC algorithm."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


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
        """
        if source not in self.data or target not in self.data:
            return None

        source_series = np.array(self.data[source])
        target_series = np.array(self.data[target])

        if len(target_series) <= max_lag + 1:
            return None

        try:
            from statsmodels.tsa.vector_ar.var_model import VAR

            combined = np.column_stack([target_series, source_series])
            model = VAR(combined)

            lag_order = min(max_lag, len(combined) // 2)
            if lag_order < 1:
                return None

            result = model.fit(lag_order)

            test_stat = result.test_causality(0, 1)
            p_value = test_stat.pvalue

            if p_value < alpha:
                strength = 1 - p_value
                return DiscoveredEdge(
                    source=source,
                    target=target,
                    statistic=test_stat.test_statistic,
                    p_value=p_value,
                    strength=strength,
                    method="granger",
                    lag=lag_order,
                )

        except Exception:
            pass

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

            original_data = self.data
            self.data = regime_data

            edges = self.discover_granger(variables)
            results[regime_name] = edges

            self.data = original_data

        return results


def rank_candidates(
    edges: list[DiscoveredEdge],
    min_strength: float = 0.5,
) -> list[DiscoveredEdge]:
    """Rank discovered edges by strength and filter by minimum threshold."""
    filtered = [e for e in edges if e.strength >= min_strength]
    return sorted(filtered, key=lambda e: e.strength, reverse=True)
