# Causal Foundation Hardening + Pearl-Lite Evaluation Harness

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the first-pass causal world model from broken/overclaiming to a solid, self-assessing foundation: fix the blockers, remove Pearl/do-calculus overclaims, replace incoherent `1−p_value` "strength" with a real effect size, add stationarity + FDR discipline to discovery, atomic persistence, and layer on a Pearl-lite evaluation harness (bootstrap edge stability + DoWhy refutation on flagship edges) that reports green/red without requiring domain expertise to interpret.

**Architecture:** Keep the existing heuristic graph/propagation as the primary LLM-legible surface. Introduce a parallel **evaluation pipeline** (`causal/evaluation.py`) that runs nightly alongside discovery and writes per-edge metadata (`stability_score`, `refutation_results`, `last_evaluated`). Estimation-grade rigor (DoWhy linear_regression w/ backdoor adjustment + refutation tests) is applied only to a small, explicit registry of "flagship" edges. Preprocessing (ADF stationarity → auto-differencing) and Benjamini-Hochberg FDR correction gate every discovery run. Persistence switches to atomic write-then-rename.

**Tech Stack:** Python 3.11+, numpy/scipy, statsmodels (ADF, VAR — already transitively present), pytest. New deps: `dowhy` (for refutation), `pandas` (DoWhy requires it; also used for alignment in preprocessing). Lives inside `core/sophia_episto` and `services/sophia_arithmos`.

**Scope boundaries:**
- Data scope: USD-only macro, G10 FX, US fixed income, index equity (no single names). Informs flagship edge selection only.
- Out of scope (explicit, do not expand this plan): regime-conditional edge activation at query time, Sophia Prima prompt-shape changes, dashboard/frontend surfacing of evaluation state, series-id ↔ concept mapping layer (today's gap between discovery and priors is noted but deferred — a separate plan).

**Pre-execution:** Create a worktree (`superpowers:using-git-worktrees`) if you want isolation. Not strictly required since work is not time-sensitive and touches no shared infra.

---

## File Structure

**Modified:**
- `core/sophia_episto/src/sophia_episto/causal/graph.py` — fix method name bug; atomic writes; edge metadata
- `core/sophia_episto/src/sophia_episto/causal/edge.py` — add `stability_score`, `refutation_results`, `last_evaluated` fields
- `core/sophia_episto/src/sophia_episto/causal/discovery.py` — fix `Observation` construction; add FDR; wire preprocessing
- `core/sophia_episto/src/sophia_episto/causal/inference.py` — rename `forward_simulate`→`forward_propagate`, remove Pearl overclaims
- `core/sophia_episto/src/sophia_episto/causal_service.py` — fix SyntaxError; integrate evaluation; new `run_evaluation()`
- `core/sophia_episto/src/sophia_episto/causal/__init__.py` — export new symbols
- `core/sophia_episto/pyproject.toml` — add dowhy, pandas, statsmodels
- `services/sophia_arithmos/src/sophia_arithmos/computations/causality.py` — replace `1−p` with effect-size; add `CausalStrength` computation
- `services/sophia_arithmos/src/sophia_arithmos/computations/__init__.py` — register `CausalStrength`
- `agents/sophia_prima/src/sophia/episto_adapter.py` — expose evaluation state via `get_causal_graph_state`

**Created:**
- `core/sophia_episto/src/sophia_episto/causal/preprocessing.py` — ADF stationarity + auto-differencing
- `core/sophia_episto/src/sophia_episto/causal/effect_size.py` — standardized β, partial R²
- `core/sophia_episto/src/sophia_episto/causal/evaluation.py` — bootstrap stability + DoWhy refutation orchestration
- `core/sophia_episto/src/sophia_episto/causal/flagship.py` — flagship edge registry
- `core/sophia_episto/tests/__init__.py` — empty, enables test package
- `core/sophia_episto/tests/test_causal/__init__.py` — empty
- `core/sophia_episto/tests/test_causal/test_edge.py`
- `core/sophia_episto/tests/test_causal/test_graph.py`
- `core/sophia_episto/tests/test_causal/test_preprocessing.py`
- `core/sophia_episto/tests/test_causal/test_effect_size.py`
- `core/sophia_episto/tests/test_causal/test_discovery.py`
- `core/sophia_episto/tests/test_causal/test_inference.py`
- `core/sophia_episto/tests/test_causal/test_evaluation.py`
- `core/sophia_episto/tests/test_causal/test_service.py`

---

## Phase 0 — Unblock

### Task 1: Fix SyntaxError in `causal_service.py`

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal_service.py:83-108`
- Test: `core/sophia_episto/tests/test_causal/test_service.py`

- [ ] **Step 1: Write the failing test**

Create `core/sophia_episto/tests/__init__.py` (empty) and `core/sophia_episto/tests/test_causal/__init__.py` (empty) first.

Create `core/sophia_episto/tests/test_causal/test_service.py`:

```python
"""Smoke and behavior tests for CausalWorldModelService."""
from __future__ import annotations


def test_service_module_imports():
    """The service module must parse and import without errors."""
    import sophia_episto.causal_service as svc  # noqa: F401
    assert hasattr(svc, "CausalWorldModelService")
```

- [ ] **Step 2: Run the test to confirm it fails**

```
cd core/sophia_episto
pytest tests/test_causal/test_service.py::test_service_module_imports -x
```

Expected: `IndentationError: unexpected indent` at `causal_service.py:98`.

- [ ] **Step 3: Fix the indentation + wire the hypothesis call properly**

Replace `causal_service.py:83-108` with:

```python
            for edge in discovered:
                from sophia_episto.causal.edge import CausalEdge

                new_edge = CausalEdge(
                    source=edge.source,
                    target=edge.target,
                    probability=edge.strength,
                    strength=edge.strength,
                    p_value=edge.p_value,
                    confidence=0.5,
                    mechanism=f"Discovered via Granger causality (p={edge.p_value:.3f})",
                )
                self.graph.add_edge(new_edge)
                results["edges_updated"] += 1

                self.hypothesis_generator.generate_from_discovered_edge(
                    edge_id=f"{edge.source}-{edge.target}",
                    source=edge.source,
                    target=edge.target,
                    strength=edge.strength,
                    mechanism=new_edge.mechanism,
                )
                results["hypotheses_generated"] += 1
```

- [ ] **Step 4: Run the test to confirm it passes**

```
pytest tests/test_causal/test_service.py::test_service_module_imports -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal_service.py \
        core/sophia_episto/tests/__init__.py \
        core/sophia_episto/tests/test_causal/__init__.py \
        core/sophia_episto/tests/test_causal/test_service.py
git commit -m "fix: repair SyntaxError in causal_service hypothesis loop"
```

---

### Task 2: Fix missing `_bayesian_update` in `CausalGraph.update_posteriors`

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/graph.py:133-141`
- Test: `core/sophia_episto/tests/test_causal/test_graph.py`

- [ ] **Step 1: Write the failing test**

Create `core/sophia_episto/tests/test_causal/test_graph.py`:

```python
"""Tests for CausalGraph."""
from __future__ import annotations

from sophia_episto.causal.edge import CausalEdge
from sophia_episto.causal.graph import CausalGraph


def test_update_posteriors_does_not_raise():
    g = CausalGraph()
    g.add_edge(CausalEdge(source="a", target="b", probability=0.5, strength=0.3, confidence=0.7))
    # Prior behavior: calling update_posteriors should not AttributeError.
    g.update_posteriors()
    edge = g.get_edge("a", "b")
    assert edge is not None
    # Probability remains in [0,1].
    assert 0.0 <= edge.probability <= 1.0
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_graph.py::test_update_posteriors_does_not_raise -x
```
Expected: `AttributeError: 'CausalGraph' object has no attribute '_bayesian_update'`.

- [ ] **Step 3: Rename the call site to the method that exists**

In `graph.py:133-141`, replace:

```python
    def update_posteriors(self) -> None:
        """Update all edge posteriors using Bayesian inference."""
        for edge in self.edges:
            edge.probability = self._bayesian_update(
                edge.probability,
                edge.strength,
                edge.confidence,
            )
        self.updated_at = datetime.now(UTC)
```

with:

```python
    def update_posteriors(self) -> None:
        """Re-blend every edge's probability with its current strength/confidence.

        This is a heuristic re-blend using `_blend_prior_with_evidence`, NOT a
        Bayesian posterior update. Safe to call repeatedly; idempotent when
        strength and confidence are unchanged.
        """
        for edge in self.edges:
            edge.probability = self._blend_prior_with_evidence(
                edge.probability,
                edge.strength,
                edge.confidence,
            )
        self.updated_at = datetime.now(UTC)
```

- [ ] **Step 4: Run the test to confirm it passes**

```
pytest tests/test_causal/test_graph.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/graph.py \
        core/sophia_episto/tests/test_causal/test_graph.py
git commit -m "fix: call existing blend helper in update_posteriors; drop phantom _bayesian_update"
```

---

### Task 3: Fix `Observation` construction in `discovery.py`

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/discovery.py:65-78`
- Test: `core/sophia_episto/tests/test_causal/test_discovery.py`

`Observation` is defined in `sophia_arithmos/core/types.py:29-35` as `{date: date, value: float}`. The current discovery code passes `id=`, `timestamp=` — that TypeError is silently swallowed by the broad `except (ImportError, ValueError)`.

- [ ] **Step 1: Write the failing test**

Create `core/sophia_episto/tests/test_causal/test_discovery.py`:

```python
"""Tests for CausalDiscovery."""
from __future__ import annotations

import numpy as np

from sophia_episto.causal.discovery import CausalDiscovery


def test_granger_test_returns_edge_for_strongly_causal_pair():
    """When x strongly Granger-causes y, we must return a DiscoveredEdge."""
    rng = np.random.default_rng(42)
    n = 200
    x = rng.standard_normal(n)
    # y[t] = 0.8 * x[t-1] + small noise — x strongly causes y.
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = 0.8 * x[t - 1] + 0.1 * rng.standard_normal()

    disc = CausalDiscovery({"x": x.tolist(), "y": y.tolist()})
    edge = disc.granger_test("x", "y", max_lag=3, alpha=0.05)
    assert edge is not None, "Granger test must detect the causal relationship"
    assert edge.source == "x"
    assert edge.target == "y"
    assert 0.0 <= edge.p_value <= 1.0
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_discovery.py::test_granger_test_returns_edge_for_strongly_causal_pair -x
```
Expected: FAIL — returns None because `Observation(id=..., timestamp=..., value=...)` raises TypeError which is silenced.

- [ ] **Step 3: Fix the construction**

In `discovery.py:65-78`, replace:

```python
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
```

with:

```python
            import json
            from datetime import date, timedelta

            from sophia_arithmos.computations.causality import GrangerCausality
            from sophia_arithmos.core.types import Observation, OutputMode

            base_date = date(2024, 1, 1)
            observations = [
                Observation(date=base_date + timedelta(days=i), value=v)
                for i, v in enumerate(target_values)
            ]
```

Also tighten the exception at `discovery.py:104` — change `except (ImportError, ValueError)` to `except (ImportError, ValueError, TypeError) as exc:` so we still swallow at the edge level but also log TypeError if it re-emerges.

- [ ] **Step 4: Run the test to confirm it passes**

```
pytest tests/test_causal/test_discovery.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/discovery.py \
        core/sophia_episto/tests/test_causal/test_discovery.py
git commit -m "fix: construct Observation with correct {date,value} schema in granger_test"
```

---

### Task 4: End-to-end smoke test for `CausalWorldModelService`

**Files:**
- Modify: `core/sophia_episto/tests/test_causal/test_service.py`

- [ ] **Step 1: Add a round-trip smoke test**

Append to `test_service.py`:

```python
import json
import numpy as np
import pytest
from pathlib import Path

from sophia_episto.causal.graph import CausalGraph
from sophia_episto.causal.edge import expert_priors
from sophia_episto.causal_service import CausalWorldModelService


@pytest.fixture
def isolated_save_graph(tmp_path, monkeypatch):
    """Redirect every save_graph call to tmp_path and prevent load_graph
    from pulling in the real on-disk file. Yields the tmp target path."""
    target = tmp_path / "graph.json"

    def _fake_save(g, path=None):
        out = path or target
        out.write_text(json.dumps(g.to_dict()))
        return out

    monkeypatch.setattr("sophia_episto.causal.graph.save_graph", _fake_save)
    monkeypatch.setattr("sophia_episto.causal_service.save_graph", _fake_save)
    monkeypatch.setattr(
        "sophia_episto.causal_service.load_graph", lambda path=None: None
    )
    return target


def test_service_initialize_and_query_with_priors(isolated_save_graph):
    """Service must initialize with expert priors and answer a query."""
    svc = CausalWorldModelService()
    svc.initialize()

    result = svc.query("inflation", "policy")
    assert result["source"] == "inflation"
    assert result["target"] == "policy"
    assert result["direct_strength"] > 0.0  # prior exists
    assert "explanation" in result


def test_service_daily_batch_on_empty_data_does_not_error(isolated_save_graph):
    svc = CausalWorldModelService(graph=CausalGraph(edges=expert_priors()))
    # No ingested data — batch should log 0 edges updated, not crash.
    result = svc.run_daily_batch()
    assert result["edges_updated"] == 0
    assert result["hypotheses_generated"] == 0
```

- [ ] **Step 2: Run the tests**

```
pytest tests/test_causal/test_service.py -x
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add core/sophia_episto/tests/test_causal/test_service.py
git commit -m "test: service initializes with priors and answers a query"
```

---

## Phase 1 — Remove Pearl / do-calculus overclaims

### Task 5: Rename and redocument to match what the code actually does

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/graph.py`
- Modify: `core/sophia_episto/src/sophia_episto/causal/inference.py`
- Modify: `core/sophia_episto/src/sophia_episto/causal_service.py`
- Modify: `agents/sophia_prima/src/sophia/episto_adapter.py`
- Test: `core/sophia_episto/tests/test_causal/test_inference.py`

- [ ] **Step 1: Write the failing test for the rename**

Create `core/sophia_episto/tests/test_causal/test_inference.py`:

```python
"""Tests for CausalInference and graph propagation."""
from __future__ import annotations

import pytest

from sophia_episto.causal.edge import CausalEdge
from sophia_episto.causal.graph import CausalGraph
from sophia_episto.causal.inference import CausalInference


def test_forward_propagate_exists_and_forward_simulate_removed():
    g = CausalGraph()
    g.add_edge(CausalEdge(source="a", target="b", probability=0.5))
    assert hasattr(g, "forward_propagate")
    assert not hasattr(g, "forward_simulate"), "forward_simulate must be renamed"


def test_forward_propagate_merges_intervention_with_observation():
    g = CausalGraph()
    g.add_edge(CausalEdge(source="x", target="y", probability=0.8))
    g.add_edge(CausalEdge(source="y", target="z", probability=0.5))

    result = g.forward_propagate(intervention={"x": 1.0}, observation={"y": 0.1, "z": 0.1})
    assert result["x"] == 1.0  # intervention preserved
    # z propagates via x -> y -> z with probabilities 0.8 * 0.5 = 0.4
    assert pytest.approx(result["z"], rel=1e-6) == 0.4
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_inference.py -x
```
Expected: FAIL — `forward_propagate` does not exist.

- [ ] **Step 3: Rename and redocument in `graph.py`**

In `graph.py`, replace the `forward_simulate` method (lines 183-210) with:

```python
    def forward_propagate(
        self,
        intervention: dict[str, float],
        observation: dict[str, float],
    ) -> dict[str, float]:
        """Heuristic forward propagation from a set-value on intervention nodes.

        This is NOT Pearl do-calculus. No graph surgery, no confounder
        adjustment. It overlays `intervention` on `observation` and
        path-multiplies edge probabilities to reach descendants.

        Args:
            intervention: Nodes to clamp to a value (acts like `do()` only in the
                trivial sense that these nodes are overwritten).
            observation: Baseline values for other nodes.

        Returns:
            Merged dict of propagated values.
        """
        result = observation.copy()
        result.update(intervention)

        for node, value in intervention.items():
            effects = self.propagate_influence(node, value)
            for affected_node, affected_value in effects.items():
                if affected_node in intervention:
                    continue
                result[affected_node] = affected_value

        return result
```

- [ ] **Step 4: Update all call sites**

Search & replace `forward_simulate` → `forward_propagate` in:

- `core/sophia_episto/src/sophia_episto/causal/inference.py:172`
- Any other occurrence (`grep -rn forward_simulate core/ agents/ services/`)

Also in `graph.py:13-18`, replace the class docstring:

```python
class CausalGraph:
    """Heuristic belief graph with Bayesian-flavored edge blending.

    This is NOT a Pearl-style structural causal model. It manages nodes and
    directed edges with per-edge `probability`, `confidence`, and `strength`,
    and supports heuristic forward propagation. Use `CausalInference` for
    path-analysis queries.
    """
```

In `inference.py:22-30`, replace the `CausalInference` docstring:

```python
class CausalInference:
    """Heuristic inference over a CausalGraph.

    This class does NOT implement do-calculus or Pearl-style counterfactuals.
    It provides:
    - Direct edge strength lookup
    - Path-product influence sums
    - Mediator/confounder structural enumeration (shape, not effect)
    """
```

In `causal_service.py:23-30`, replace the `CausalWorldModelService` docstring:

```python
class CausalWorldModelService:
    """Service for managing the heuristic causal belief graph.

    Provides:
    - Scheduled batch discovery (Granger + FDR) and belief blending
    - Integration point for Sophia Prima causal queries
    - Hypothesis generation from discovered edges
    - Pearl-lite evaluation harness (bootstrap stability + DoWhy refutation on
      flagship edges) that surfaces per-edge green/red signals without making
      Pearl-identification claims across the full graph.
    """
```

- [ ] **Step 5: Run all tests**

```
pytest tests/test_causal/ -x
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A core/sophia_episto agents/sophia_prima/src/sophia/episto_adapter.py
git commit -m "refactor: rename forward_simulate to forward_propagate; drop Pearl/do-calculus overclaims"
```

---

## Phase 2 — Correctness foundations

### Task 6: Stationarity preprocessing module

**Files:**
- Create: `core/sophia_episto/src/sophia_episto/causal/preprocessing.py`
- Test: `core/sophia_episto/tests/test_causal/test_preprocessing.py`
- Modify: `core/sophia_episto/pyproject.toml` (add `statsmodels`, `pandas`)

- [ ] **Step 1: Add statsmodels and pandas to deps**

In `core/sophia_episto/pyproject.toml`, replace the `dependencies` list with:

```toml
dependencies = [
    "numpy>=1.24.0",
    "scipy>=1.11.0",
    "pandas>=2.0.0",
    "statsmodels>=0.14.0",
    "sophia-arithmos",
]
```

Reinstall:

```
cd core/sophia_episto && pip install -e .
```

- [ ] **Step 2: Write the failing test**

Create `core/sophia_episto/tests/test_causal/test_preprocessing.py`:

```python
"""Tests for stationarity preprocessing."""
from __future__ import annotations

import numpy as np
import pytest

from sophia_episto.causal.preprocessing import (
    StationarityReport,
    is_stationary,
    prepare_for_discovery,
)


def test_is_stationary_detects_white_noise():
    rng = np.random.default_rng(0)
    y = rng.standard_normal(200).tolist()
    report = is_stationary(y)
    assert report.stationary is True
    assert report.p_value < 0.05


def test_is_stationary_flags_random_walk():
    rng = np.random.default_rng(0)
    y = np.cumsum(rng.standard_normal(200)).tolist()
    report = is_stationary(y)
    assert report.stationary is False


def test_prepare_for_discovery_differences_nonstationary_series():
    rng = np.random.default_rng(0)
    stationary = rng.standard_normal(200).tolist()
    walk = np.cumsum(rng.standard_normal(200)).tolist()
    data = {"stationary": stationary, "walk": walk}

    prepared, report = prepare_for_discovery(data)
    # Stationary series unchanged; walk differenced (length n-1).
    assert prepared["stationary"] == stationary
    assert len(prepared["walk"]) == len(walk) - 1
    assert "walk" in report.differenced
    assert "stationary" not in report.differenced


def test_prepare_for_discovery_aligns_lengths():
    """All returned series must share the same length for discovery."""
    rng = np.random.default_rng(0)
    data = {
        "a": rng.standard_normal(200).tolist(),
        "b": np.cumsum(rng.standard_normal(200)).tolist(),
    }
    prepared, _ = prepare_for_discovery(data)
    lengths = {len(v) for v in prepared.values()}
    assert len(lengths) == 1, f"lengths diverged: {lengths}"


def test_prepare_for_discovery_double_differences_when_needed():
    rng = np.random.default_rng(0)
    # Drift + random walk = I(2)-ish.
    base = np.cumsum(np.cumsum(rng.standard_normal(250)))
    prepared, report = prepare_for_discovery({"x": base.tolist()}, max_diff=2)
    rep = is_stationary(prepared["x"])
    assert rep.stationary is True
    assert report.diff_orders["x"] >= 1
```

- [ ] **Step 3: Run the test to confirm it fails**

```
pytest tests/test_causal/test_preprocessing.py -x
```
Expected: `ModuleNotFoundError: No module named 'sophia_episto.causal.preprocessing'`.

- [ ] **Step 4: Implement `preprocessing.py`**

Create `core/sophia_episto/src/sophia_episto/causal/preprocessing.py`:

```python
"""Stationarity testing and auto-differencing for causal discovery."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class StationarityReport:
    """Result of an Augmented Dickey-Fuller (ADF) test."""

    stationary: bool
    p_value: float
    test_statistic: float
    lag: int


@dataclass
class PreprocessingReport:
    """Summary of preprocessing decisions for a batch."""

    differenced: list[str] = field(default_factory=list)
    diff_orders: dict[str, int] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)


def is_stationary(values: list[float], alpha: float = 0.05) -> StationarityReport:
    """Run ADF test. Returns StationarityReport.

    Null hypothesis of ADF: unit root (non-stationary). We reject at alpha
    to declare stationarity.
    """
    from statsmodels.tsa.stattools import adfuller

    arr = np.asarray(values, dtype=float)
    if len(arr) < 15:
        # Too short to reliably test — treat as stationary and let the
        # downstream test handle insufficient-data errors.
        return StationarityReport(stationary=True, p_value=1.0, test_statistic=0.0, lag=0)

    try:
        stat, p_value, lag, *_ = adfuller(arr, autolag="AIC")
    except (ValueError, np.linalg.LinAlgError):
        return StationarityReport(stationary=True, p_value=1.0, test_statistic=0.0, lag=0)

    return StationarityReport(
        stationary=bool(p_value < alpha),
        p_value=float(p_value),
        test_statistic=float(stat),
        lag=int(lag),
    )


def prepare_for_discovery(
    data: dict[str, list[float]],
    alpha: float = 0.05,
    max_diff: int = 2,
    min_length: int = 30,
) -> tuple[dict[str, list[float]], PreprocessingReport]:
    """Ensure every series is stationary (differencing up to `max_diff` times)
    and align all series to a common length by trimming from the front.

    Returns (prepared_data, report).
    """
    report = PreprocessingReport()
    prepared: dict[str, list[float]] = {}

    for name, values in data.items():
        arr = np.asarray(values, dtype=float)
        order = 0
        while order < max_diff:
            rep = is_stationary(arr.tolist(), alpha=alpha)
            if rep.stationary:
                break
            arr = np.diff(arr)
            order += 1

        if len(arr) < min_length:
            report.dropped.append(name)
            continue

        if order > 0:
            report.differenced.append(name)
        report.diff_orders[name] = order
        prepared[name] = arr.tolist()

    if not prepared:
        return prepared, report

    common = min(len(v) for v in prepared.values())
    prepared = {k: v[-common:] for k, v in prepared.items()}
    return prepared, report
```

- [ ] **Step 5: Run the tests**

```
pytest tests/test_causal/test_preprocessing.py -x
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/sophia_episto/pyproject.toml \
        core/sophia_episto/src/sophia_episto/causal/preprocessing.py \
        core/sophia_episto/tests/test_causal/test_preprocessing.py
git commit -m "feat: add ADF stationarity + auto-differencing preprocessing"
```

---

### Task 7: Effect-size module (replaces `strength = 1 − p_value`)

**Files:**
- Create: `core/sophia_episto/src/sophia_episto/causal/effect_size.py`
- Test: `core/sophia_episto/tests/test_causal/test_effect_size.py`

- [ ] **Step 1: Write the failing test**

Create `core/sophia_episto/tests/test_causal/test_effect_size.py`:

```python
"""Tests for effect-size estimators."""
from __future__ import annotations

import numpy as np
import pytest

from sophia_episto.causal.effect_size import (
    partial_r_squared,
    standardized_beta,
    strength_from_lagged_regression,
)


def test_standardized_beta_near_one_for_perfect_linear_relationship():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(200)
    y = 2.0 * x  # perfect
    beta = standardized_beta(x, y)
    assert pytest.approx(abs(beta), abs=0.02) == 1.0


def test_standardized_beta_near_zero_for_independent_series():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(500)
    y = rng.standard_normal(500)
    beta = standardized_beta(x, y)
    assert abs(beta) < 0.15


def test_partial_r_squared_bounded_0_1():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(200)
    y = 0.5 * x + 0.5 * rng.standard_normal(200)
    r2 = partial_r_squared(x, y)
    assert 0.0 <= r2 <= 1.0


def test_strength_from_lagged_regression_increases_with_dependence():
    """Stronger lag-1 dependence should produce larger strength."""
    rng = np.random.default_rng(0)
    n = 300
    noise = rng.standard_normal(n)

    x = rng.standard_normal(n)
    y_strong = np.zeros(n)
    y_weak = np.zeros(n)
    for t in range(1, n):
        y_strong[t] = 0.8 * x[t - 1] + 0.2 * noise[t]
        y_weak[t] = 0.1 * x[t - 1] + 0.9 * noise[t]

    s_strong = strength_from_lagged_regression(x.tolist(), y_strong.tolist(), lag=1)
    s_weak = strength_from_lagged_regression(x.tolist(), y_weak.tolist(), lag=1)
    assert s_strong > s_weak
    assert 0.0 <= s_weak <= 1.0
    assert 0.0 <= s_strong <= 1.0
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_effect_size.py -x
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `effect_size.py`**

Create `core/sophia_episto/src/sophia_episto/causal/effect_size.py`:

```python
"""Effect-size estimators for causal edge strength.

Replaces the prior `strength = 1 - p_value` convention, which is not an
effect size. These return quantities in [0,1] with honest interpretations:

- `standardized_beta`: β from OLS of z-scored y on z-scored x. Returns raw β
  (can be negative); call `abs()` if you want a magnitude.
- `partial_r_squared`: squared correlation in [0,1].
- `strength_from_lagged_regression`: partial R² from regressing y[t] on
  x[t-lag] after projecting out y's own AR(lag) dynamics — this is the
  Granger-style "incremental predictive power" expressed as a bounded
  effect-size-like quantity.
"""
from __future__ import annotations

import numpy as np


def _zscore(v: np.ndarray) -> np.ndarray:
    std = v.std(ddof=1)
    if std == 0:
        return np.zeros_like(v)
    return (v - v.mean()) / std


def standardized_beta(x: np.ndarray, y: np.ndarray) -> float:
    """Standardized OLS slope of y on x. In [-1, 1] for normally distributed pairs."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    zx = _zscore(x)
    zy = _zscore(y)
    denom = float(zx @ zx)
    if denom == 0:
        return 0.0
    return float((zx @ zy) / denom)


def partial_r_squared(x: np.ndarray, y: np.ndarray) -> float:
    """Squared Pearson correlation. Always in [0,1]."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    if x.std(ddof=1) == 0 or y.std(ddof=1) == 0:
        return 0.0
    r = float(np.corrcoef(x, y)[0, 1])
    return r * r


def strength_from_lagged_regression(
    source_values: list[float],
    target_values: list[float],
    lag: int = 1,
) -> float:
    """Partial R² of y[t] on x[t-lag] after AR(lag) projection of y.

    Returns a value in [0,1] representing the extra variance of y explained
    by past x beyond what y's own lags already explain. This is the
    Granger-style incremental predictive contribution, framed as an effect
    size rather than `1 - p_value`.
    """
    x = np.asarray(source_values, dtype=float)
    y = np.asarray(target_values, dtype=float)
    if len(x) != len(y) or len(y) <= lag + 5:
        return 0.0

    y_t = y[lag:]
    x_lag = x[:-lag]
    y_lag = y[:-lag]

    # Project out y's own AR(lag) to get "unexplained by own past" residual.
    Z = np.column_stack([np.ones(len(y_lag)), y_lag])
    try:
        coeffs, *_ = np.linalg.lstsq(Z, y_t, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    resid_y = y_t - Z @ coeffs

    # Project same AR(lag) out of x[t-lag] to isolate its contribution.
    try:
        coeffs_x, *_ = np.linalg.lstsq(Z, x_lag, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0
    resid_x = x_lag - Z @ coeffs_x

    if resid_x.std(ddof=1) == 0 or resid_y.std(ddof=1) == 0:
        return 0.0

    r = float(np.corrcoef(resid_x, resid_y)[0, 1])
    return max(0.0, min(1.0, r * r))
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_effect_size.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/effect_size.py \
        core/sophia_episto/tests/test_causal/test_effect_size.py
git commit -m "feat: introduce effect-size estimators (standardized beta, partial R-squared)"
```

---

### Task 8: Replace `1 − p_value` in `GrangerCausality`; add `CausalStrength` computation

**Files:**
- Modify: `services/sophia_arithmos/src/sophia_arithmos/computations/causality.py`
- Modify: `services/sophia_arithmos/src/sophia_arithmos/computations/__init__.py`
- Test: `services/sophia_arithmos/tests/test_computations/test_causality.py` (existing)

- [ ] **Step 1: Run the existing broken test to confirm the failure mode**

```
cd services/sophia_arithmos
pytest tests/test_computations/test_causality.py -x
```
Expected: `ImportError: cannot import name 'CausalStrength'`.

- [ ] **Step 2: Replace `strength` definition in `GrangerCausality`**

In `services/sophia_arithmos/src/sophia_arithmos/computations/causality.py:170-171`, replace:

```python
        is_causal = best_pvalue < alpha
        strength = max(0.0, 1.0 - best_pvalue) if best_pvalue < alpha else 0.0
```

with:

```python
        is_causal = best_pvalue < alpha
        # Strength = incremental predictive contribution, bounded [0,1].
        # Only reported when the effect is statistically detected; else 0.
        strength = 0.0
        if is_causal and len(y) > best_lag + 5:
            # Partial R² of y[t] on y[t-lag].
            y_t = y[best_lag:]
            y_lag = y[:-best_lag]
            if y_lag.std(ddof=1) > 0 and y_t.std(ddof=1) > 0:
                r = float(np.corrcoef(y_lag, y_t)[0, 1])
                strength = max(0.0, min(1.0, r * r))
```

In the same file, lines 229-230 of `_bivariate_granger`, replace:

```python
        strength = 1.0 - p_value if p_value < alpha else 0.0
```

with:

```python
        strength = 0.0
        if is_causal:
            # Partial R² of y[t] on x[t-lag] after projecting out y's AR(lag).
            # Kept inline (not imported from sophia_episto) to preserve the
            # Arithmos -> Episto dependency direction.
            lag = min(lag_order, 3)
            if len(y) > lag + 5 and len(x) == len(y):
                y_t = y[lag:]
                y_lag = y[:-lag]
                x_lag = x[:-lag]
                Z = np.column_stack([np.ones(len(y_lag)), y_lag])
                try:
                    coeffs_y, *_ = np.linalg.lstsq(Z, y_t, rcond=None)
                    coeffs_x, *_ = np.linalg.lstsq(Z, x_lag, rcond=None)
                    resid_y = y_t - Z @ coeffs_y
                    resid_x = x_lag - Z @ coeffs_x
                    if resid_x.std(ddof=1) > 0 and resid_y.std(ddof=1) > 0:
                        r = float(np.corrcoef(resid_x, resid_y)[0, 1])
                        strength = max(0.0, min(1.0, r * r))
                except np.linalg.LinAlgError:
                    strength = 0.0
```

Note: the partial-R² computation is intentionally duplicated inline here (≈15 LOC) rather than imported from `sophia_episto.causal.effect_size`, to preserve the architectural rule that Arithmos is the primitive layer and Episto depends on it — not the reverse.

- [ ] **Step 3: Add the `CausalStrength` computation**

Append to `causality.py` (after `_f_cdf`):

```python
@registry.register
class CausalStrength(Computation):
    """Estimate a directional effect-size between two series.

    Supports two methods:
    - `regression`: standardized OLS slope of target on source.
    - `correlation`: squared Pearson correlation.

    Both return a bounded [0,1] or [-1,1] value in the result summary.
    This is NOT a causal effect in the Pearl sense; it is a predictive
    association metric intended for heuristic edge scoring.
    """

    name = "causal_strength"
    description = "Directional effect-size between two series (regression or correlation)"
    params = {
        "source_series": ParamSpec(
            type="string", description="Source series name", required=True
        ),
        "target_series": ParamSpec(
            type="string", description="Target series name", required=True
        ),
        "source_values": ParamSpec(
            type="string",
            description="JSON-encoded list of source values (if not derivable from data)",
            required=False,
        ),
        "method": ParamSpec(
            type="string",
            description="regression | correlation",
            default="regression",
        ),
    }
    precision_type = PrecisionType.DEFAULT

    def compute(
        self,
        data: list[Observation],
        params: dict[str, Any],
        output: OutputMode,
    ) -> ComputationResult:
        import json

        method = params.get("method", "regression")
        source = params["source_series"]
        target = params["target_series"]

        y = np.array([obs.value for obs in data])
        src_str = params.get("source_values")
        if src_str:
            try:
                x = np.array(json.loads(src_str))
            except (json.JSONDecodeError, TypeError):
                x = y  # degenerate: self-regression
        else:
            # Self-regression — not meaningful but keeps the API stable.
            x = y

        if len(x) != len(y):
            m = min(len(x), len(y))
            x = x[-m:]
            y = y[-m:]

        if len(y) < 3:
            strength = 0.0
        elif method == "correlation":
            if x.std(ddof=1) == 0 or y.std(ddof=1) == 0:
                strength = 0.0
            else:
                r = float(np.corrcoef(x, y)[0, 1])
                strength = max(0.0, min(1.0, r * r))
        else:  # regression
            if x.std(ddof=1) == 0 or y.std(ddof=1) == 0:
                strength = 0.0
            else:
                zx = (x - x.mean()) / x.std(ddof=1)
                zy = (y - y.mean()) / y.std(ddof=1)
                denom = float(zx @ zx)
                strength = float((zx @ zy) / denom) if denom else 0.0

        return ComputationResult(
            series=None,
            latest=None,
            summary={
                "source_series": source,
                "target_series": target,
                "method": method,
                "strength": float(strength),
                "n_observations": int(len(y)),
            },
            metadata={"computation": "causal_strength"},
        )
```

In `services/sophia_arithmos/src/sophia_arithmos/computations/__init__.py`, add:

```python
from sophia_arithmos.computations.causality import CausalStrength, GrangerCausality  # noqa: F401
```

(Append if not already present; otherwise extend the existing import.)

- [ ] **Step 4: Run the tests**

```
cd services/sophia_arithmos
pytest tests/test_computations/test_causality.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/sophia_arithmos/src/sophia_arithmos/computations/causality.py \
        services/sophia_arithmos/src/sophia_arithmos/computations/__init__.py
git commit -m "feat(arithmos): replace 1-p strength with effect-size; add CausalStrength"
```

---

### Task 9: Benjamini-Hochberg FDR correction in `discover_granger`

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/discovery.py`
- Test: `core/sophia_episto/tests/test_causal/test_discovery.py`

- [ ] **Step 1: Write the failing test**

Append to `core/sophia_episto/tests/test_causal/test_discovery.py`:

```python
def test_discover_granger_applies_fdr_correction():
    """Under the null (all independent series), FDR correction should keep
    the expected-false-positive count well below the naive alpha count."""
    rng = np.random.default_rng(0)
    n = 150
    variables = [f"v{i}" for i in range(8)]
    data = {v: rng.standard_normal(n).tolist() for v in variables}
    disc = CausalDiscovery(data)
    edges = disc.discover_granger(variables, max_lag=3, alpha=0.05, fdr=True)

    # Naive would expect ~0.05 * 8*7 = 2.8 false positives. FDR should
    # typically prune these to 0-1.
    assert len(edges) <= 2

    edges_uncorrected = disc.discover_granger(
        variables, max_lag=3, alpha=0.05, fdr=False
    )
    # FDR should be at least as strict as no correction.
    assert len(edges) <= len(edges_uncorrected)
```

- [ ] **Step 2: Run the test to confirm it fails**

```
cd core/sophia_episto
pytest tests/test_causal/test_discovery.py::test_discover_granger_applies_fdr_correction -x
```
Expected: FAIL — `fdr` kwarg not supported.

- [ ] **Step 3: Add FDR correction to `discover_granger`**

Replace `discover_granger` in `discovery.py:109-127` with:

```python
    def discover_granger(
        self,
        variables: list[str],
        max_lag: int = 5,
        alpha: float = 0.05,
        fdr: bool = True,
    ) -> list[DiscoveredEdge]:
        """Run Granger causality discovery across all ordered variable pairs.

        When `fdr=True`, applies Benjamini-Hochberg correction across all
        tested pairs to control false discovery rate at `alpha`.
        """
        candidates: list[DiscoveredEdge] = []
        for var1 in variables:
            for var2 in variables:
                if var1 == var2:
                    continue
                result = self.granger_test(var1, var2, max_lag, alpha=1.0)
                # alpha=1.0 so we collect all pairs and correct below.
                if result is not None:
                    candidates.append(result)

        if not candidates:
            return []

        if not fdr:
            return [e for e in candidates if e.p_value < alpha]

        # Benjamini-Hochberg.
        ordered = sorted(candidates, key=lambda e: e.p_value)
        m = len(ordered)
        threshold_idx = -1
        for i, e in enumerate(ordered, start=1):
            if e.p_value <= (i / m) * alpha:
                threshold_idx = i
        if threshold_idx < 0:
            return []
        return ordered[:threshold_idx]
```

The `granger_test` already returns `None` when `is_granger_causal` is False. To allow BH correction, we need `granger_test` to return the edge even under the null. Modify `granger_test` (lines 93-102 of `discovery.py`) from:

```python
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
```

to:

```python
            detected = bool(summary.get("is_granger_causal")) and summary.get("p_value", 1.0) < alpha
            if detected or alpha >= 1.0:
                return DiscoveredEdge(
                    source=source,
                    target=target,
                    statistic=summary.get("test_statistic", 0),
                    p_value=summary.get("p_value", 1.0),
                    strength=summary.get("strength", 0),
                    method="granger",
                    lag=summary.get("best_lag", max_lag),
                )
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_discovery.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/discovery.py \
        core/sophia_episto/tests/test_causal/test_discovery.py
git commit -m "feat: apply Benjamini-Hochberg FDR correction across granger pairs"
```

---

### Task 10: Atomic writes for `save_graph`

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/graph.py`
- Test: `core/sophia_episto/tests/test_causal/test_graph.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_causal/test_graph.py`:

```python
from pathlib import Path
import json

from sophia_episto.causal.graph import save_graph, load_graph


def test_save_graph_is_atomic(tmp_path: Path, monkeypatch):
    """A failed write must not leave a partial file in place."""
    g = CausalGraph()
    g.add_edge(CausalEdge(source="a", target="b", probability=0.5))
    target = tmp_path / "graph.json"
    save_graph(g, target)
    assert target.exists()
    loaded = load_graph(target)
    assert loaded is not None
    assert any(e.source == "a" and e.target == "b" for e in loaded.edges)


def test_save_graph_does_not_leak_tempfile(tmp_path: Path):
    g = CausalGraph()
    save_graph(g, tmp_path / "graph.json")
    # No leftover *.tmp or *.partial siblings.
    siblings = list(tmp_path.glob("*"))
    assert all(not s.name.endswith(".tmp") for s in siblings)
```

- [ ] **Step 2: Run the test to confirm the atomic guarantee is not yet enforced**

```
pytest tests/test_causal/test_graph.py -x
```
(The first test may already pass. The second is the real guard — we want to ensure no tempfile survives even under future exceptions.)

- [ ] **Step 3: Replace `save_graph` body**

In `graph.py:250-270`, replace the function body with:

```python
def save_graph(graph: CausalGraph, path: Path | None = None) -> Path:
    """Save graph to JSON file using atomic write-then-rename.

    Args:
        graph: The causal graph to save
        path: Optional custom path, defaults to data/causal_graph/graph.json

    Returns:
        Path where the graph was saved
    """
    import os
    import tempfile

    if path is None:
        path = (
            Path(__file__).resolve().parents[5] / "data" / "causal_graph" / "graph.json"
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a tempfile in the same directory (atomic rename requires same FS).
    fd, tmp_name = tempfile.mkstemp(
        prefix=".graph-", suffix=".json.tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(graph.to_dict(), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        raise

    return path
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_graph.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/graph.py \
        core/sophia_episto/tests/test_causal/test_graph.py
git commit -m "feat: atomic write-then-rename in save_graph; fsync before rename"
```

---

## Phase 3 — Bootstrap edge stability

### Task 11: Add evaluation metadata to `CausalEdge`

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/edge.py`
- Test: `core/sophia_episto/tests/test_causal/test_edge.py`

- [ ] **Step 1: Write the failing test**

Create `core/sophia_episto/tests/test_causal/test_edge.py`:

```python
"""Tests for CausalEdge."""
from __future__ import annotations

from datetime import UTC, datetime

from sophia_episto.causal.edge import CausalEdge


def test_edge_has_evaluation_metadata_fields():
    e = CausalEdge(source="a", target="b")
    assert e.stability_score is None
    assert e.refutation_results == {}
    assert e.last_evaluated is None


def test_edge_roundtrips_evaluation_metadata():
    when = datetime(2026, 4, 17, tzinfo=UTC)
    e = CausalEdge(
        source="a",
        target="b",
        stability_score=0.87,
        refutation_results={"placebo": "pass", "random_common_cause": "pass"},
        last_evaluated=when,
    )
    d = e.to_dict()
    assert d["stability_score"] == 0.87
    assert d["refutation_results"]["placebo"] == "pass"
    assert d["last_evaluated"] == when.isoformat()

    restored = CausalEdge.from_dict(d)
    assert restored.stability_score == 0.87
    assert restored.refutation_results["placebo"] == "pass"
    assert restored.last_evaluated == when
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_edge.py -x
```
Expected: FAIL — fields don't exist.

- [ ] **Step 3: Add the fields**

In `edge.py`, update the imports at the top:

```python
from datetime import datetime
```

Add three fields to the `CausalEdge` dataclass (after `regime_dependent`):

```python
    stability_score: float | None = None
    refutation_results: dict[str, str] = field(default_factory=dict)
    last_evaluated: datetime | None = None
```

Update `to_dict` to serialize them:

```python
        return {
            "source": self.source,
            "target": self.target,
            "relationship_key": self.relationship_key,
            "probability": self.probability,
            "confidence": self.confidence,
            "strength": self.strength,
            "p_value": self.p_value,
            "mechanism": self.mechanism,
            "conditions": self.conditions,
            "regime_dependent": self.regime_dependent,
            "stability_score": self.stability_score,
            "refutation_results": self.refutation_results,
            "last_evaluated": self.last_evaluated.isoformat() if self.last_evaluated else None,
        }
```

Update `from_dict`:

```python
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalEdge:
        last_eval_raw = data.get("last_evaluated")
        last_eval = datetime.fromisoformat(last_eval_raw) if last_eval_raw else None
        return cls(
            source=data["source"],
            target=data["target"],
            relationship_key=tuple(data["relationship_key"])
            if data.get("relationship_key")
            else None,
            probability=data.get("probability", 0.5),
            confidence=data.get("confidence", 0.0),
            strength=data.get("strength", 0.0),
            p_value=data.get("p_value"),
            mechanism=data.get("mechanism", ""),
            conditions=data.get("conditions", {}),
            regime_dependent=data.get("regime_dependent", False),
            stability_score=data.get("stability_score"),
            refutation_results=data.get("refutation_results", {}),
            last_evaluated=last_eval,
        )
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/ -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/edge.py \
        core/sophia_episto/tests/test_causal/test_edge.py
git commit -m "feat: add stability_score, refutation_results, last_evaluated to CausalEdge"
```

---

### Task 12: Bootstrap stability evaluator

**Files:**
- Create: `core/sophia_episto/src/sophia_episto/causal/evaluation.py`
- Test: `core/sophia_episto/tests/test_causal/test_evaluation.py`

- [ ] **Step 1: Write the failing test**

Create `core/sophia_episto/tests/test_causal/test_evaluation.py`:

```python
"""Tests for the Pearl-lite evaluation harness."""
from __future__ import annotations

import numpy as np

from sophia_episto.causal.evaluation import (
    BootstrapStabilityReport,
    run_bootstrap_stability,
)


def test_bootstrap_stability_detects_strong_edge():
    rng = np.random.default_rng(0)
    n = 200
    x = rng.standard_normal(n)
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = 0.8 * x[t - 1] + 0.1 * rng.standard_normal()

    report = run_bootstrap_stability(
        data={"x": x.tolist(), "y": y.tolist()},
        variables=["x", "y"],
        n_resamples=30,
        block_size=20,
        seed=0,
    )
    assert isinstance(report, BootstrapStabilityReport)
    # The x -> y edge should appear in most resamples.
    key = ("x", "y")
    assert report.edge_frequency.get(key, 0.0) > 0.5


def test_bootstrap_stability_does_not_invent_edges_for_independent_series():
    rng = np.random.default_rng(0)
    n = 200
    data = {
        "a": rng.standard_normal(n).tolist(),
        "b": rng.standard_normal(n).tolist(),
    }
    report = run_bootstrap_stability(
        data=data, variables=["a", "b"], n_resamples=30, block_size=20, seed=1
    )
    # No edge should dominate under the null.
    for freq in report.edge_frequency.values():
        assert freq < 0.6
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_evaluation.py -x
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `evaluation.py` (bootstrap half only for now)**

Create `core/sophia_episto/src/sophia_episto/causal/evaluation.py`:

```python
"""Pearl-lite evaluation harness: bootstrap edge stability + DoWhy refutation.

Bootstrap stability: resample the data using a moving-block bootstrap (to
preserve short-run autocorrelation), rerun Granger+FDR discovery on each
resample, and record the fraction of resamples in which each edge was
discovered. This is the primary automated green/red signal for
"is this edge spurious?"

DoWhy refutation: applied only to a small flagship edge set. See
`flagship.py` and Task 15-17.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from sophia_episto.causal.discovery import CausalDiscovery
from sophia_episto.causal.preprocessing import prepare_for_discovery


@dataclass
class BootstrapStabilityReport:
    n_resamples: int
    block_size: int
    edge_frequency: dict[tuple[str, str], float] = field(default_factory=dict)
    edges_stable: list[tuple[str, str]] = field(default_factory=list)
    edges_unstable: list[tuple[str, str]] = field(default_factory=list)


def _moving_block_resample(
    series: np.ndarray, block_size: int, rng: np.random.Generator
) -> np.ndarray:
    n = len(series)
    if block_size >= n:
        return series.copy()
    n_blocks = (n // block_size) + 1
    starts = rng.integers(0, n - block_size + 1, size=n_blocks)
    blocks = [series[s : s + block_size] for s in starts]
    out = np.concatenate(blocks)
    return out[:n]


def run_bootstrap_stability(
    data: dict[str, list[float]],
    variables: list[str],
    n_resamples: int = 100,
    block_size: int = 20,
    max_lag: int = 3,
    alpha: float = 0.05,
    stability_threshold: float = 0.6,
    seed: int | None = None,
) -> BootstrapStabilityReport:
    """Run moving-block bootstrap stability analysis.

    Returns per-edge discovery frequency across `n_resamples` bootstrap
    replications. Edges with frequency >= `stability_threshold` are listed
    as stable.
    """
    rng = np.random.default_rng(seed)
    counter: Counter[tuple[str, str]] = Counter()

    # Preprocess once so every bootstrap samples from comparable (stationary) input.
    prepared, _ = prepare_for_discovery(data)
    prepared_vars = [v for v in variables if v in prepared]
    if len(prepared_vars) < 2:
        return BootstrapStabilityReport(
            n_resamples=n_resamples, block_size=block_size
        )

    arrays = {k: np.asarray(v) for k, v in prepared.items() if k in prepared_vars}

    for _ in range(n_resamples):
        resampled = {
            k: _moving_block_resample(arr, block_size, rng).tolist()
            for k, arr in arrays.items()
        }
        disc = CausalDiscovery(resampled)
        edges = disc.discover_granger(
            prepared_vars, max_lag=max_lag, alpha=alpha, fdr=True
        )
        seen_this_round: set[tuple[str, str]] = set()
        for e in edges:
            seen_this_round.add((e.source, e.target))
        for pair in seen_this_round:
            counter[pair] += 1

    freq = {pair: count / n_resamples for pair, count in counter.items()}
    stable = sorted(p for p, f in freq.items() if f >= stability_threshold)
    unstable = sorted(p for p, f in freq.items() if f < stability_threshold)

    return BootstrapStabilityReport(
        n_resamples=n_resamples,
        block_size=block_size,
        edge_frequency=freq,
        edges_stable=stable,
        edges_unstable=unstable,
    )
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_evaluation.py -x
```
Expected: PASS. (May be slow — ~5-15s. That's fine.)

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/evaluation.py \
        core/sophia_episto/tests/test_causal/test_evaluation.py
git commit -m "feat: moving-block bootstrap stability evaluator"
```

---

### Task 13: Write stability scores back onto edges

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/evaluation.py`
- Modify: `core/sophia_episto/tests/test_causal/test_evaluation.py`

- [ ] **Step 1: Write the failing test**

Append to `test_evaluation.py`:

```python
from datetime import UTC, datetime
from sophia_episto.causal.edge import CausalEdge
from sophia_episto.causal.graph import CausalGraph
from sophia_episto.causal.evaluation import apply_stability_to_graph


def test_apply_stability_to_graph_writes_scores_and_timestamp():
    g = CausalGraph()
    g.add_edge(CausalEdge(source="x", target="y", probability=0.5))
    g.add_edge(CausalEdge(source="x", target="z", probability=0.5))

    report = BootstrapStabilityReport(
        n_resamples=100,
        block_size=20,
        edge_frequency={("x", "y"): 0.87, ("x", "z"): 0.12},
        edges_stable=[("x", "y")],
        edges_unstable=[("x", "z")],
    )

    apply_stability_to_graph(g, report)

    e_xy = g.get_edge("x", "y")
    e_xz = g.get_edge("x", "z")
    assert e_xy.stability_score == 0.87
    assert e_xz.stability_score == 0.12
    assert e_xy.last_evaluated is not None
    assert e_xy.last_evaluated.tzinfo == UTC
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_evaluation.py::test_apply_stability_to_graph_writes_scores_and_timestamp -x
```
Expected: ImportError.

- [ ] **Step 3: Implement `apply_stability_to_graph`**

Append to `evaluation.py`:

```python
from datetime import UTC, datetime as _datetime

from sophia_episto.causal.graph import CausalGraph


def apply_stability_to_graph(
    graph: CausalGraph, report: BootstrapStabilityReport
) -> None:
    """Write stability_score and last_evaluated onto every edge present in the graph."""
    now = _datetime.now(UTC)
    for edge in graph.edges:
        key = (edge.source, edge.target)
        edge.stability_score = report.edge_frequency.get(key, 0.0)
        edge.last_evaluated = now
    graph.updated_at = now
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_evaluation.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/evaluation.py \
        core/sophia_episto/tests/test_causal/test_evaluation.py
git commit -m "feat: apply bootstrap stability scores onto graph edges"
```

---

## Phase 4 — DoWhy flagship refutation

### Task 14: Add DoWhy dependency

**Files:**
- Modify: `core/sophia_episto/pyproject.toml`

- [ ] **Step 1: Add `dowhy` to dependencies**

In `core/sophia_episto/pyproject.toml`, extend dependencies:

```toml
dependencies = [
    "numpy>=1.24.0",
    "scipy>=1.11.0",
    "pandas>=2.0.0",
    "statsmodels>=0.14.0",
    "dowhy>=0.11",
    "sophia-arithmos",
]
```

Install:

```
cd core/sophia_episto && pip install -e .
```

- [ ] **Step 2: Verify import works**

```
python -c "import dowhy; print(dowhy.__version__)"
```
Expected: prints a version >= 0.11.

- [ ] **Step 3: Commit**

```bash
git add core/sophia_episto/pyproject.toml
git commit -m "build(episto): add dowhy dependency for refutation harness"
```

---

### Task 15: Flagship edge registry

**Files:**
- Create: `core/sophia_episto/src/sophia_episto/causal/flagship.py`
- Test: extend `core/sophia_episto/tests/test_causal/test_evaluation.py`

- [ ] **Step 1: Write the failing test**

Append to `test_evaluation.py`:

```python
from sophia_episto.causal.flagship import FlagshipEdge, flagship_edges


def test_flagship_registry_matches_scope_constraints():
    edges = flagship_edges()
    assert len(edges) >= 3
    names = {(e.source, e.target) for e in edges}
    # Must cover the three pivotal macro edges.
    assert ("policy", "growth") in names
    assert ("policy", "positioning") in names
    assert ("inflation", "policy") in names
    for e in edges:
        assert e.adjustment_set is not None  # may be empty tuple, not None
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_evaluation.py::test_flagship_registry_matches_scope_constraints -x
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `flagship.py`**

Create `core/sophia_episto/src/sophia_episto/causal/flagship.py`:

```python
"""Registry of flagship edges subject to DoWhy refutation.

Flagship edges are those we want to hold to an estimation-grade standard:
linear-regression-with-backdoor estimation via DoWhy, plus placebo and
random-common-cause refutations. The adjustment set is hand-specified to
reflect the scope constraint (USD macro + G10 FX + US FI + index equity).

Keep this list small (5-10 edges). The point is a green/red signal on the
most load-bearing relationships in the graph, not global coverage.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlagshipEdge:
    source: str
    target: str
    adjustment_set: tuple[str, ...]
    rationale: str


def flagship_edges() -> list[FlagshipEdge]:
    """Return the current flagship registry.

    Adjustment sets are minimal and defensible; they do NOT claim to
    identify the full backdoor set. They exist so the linear_regression
    estimator in DoWhy has *some* controls beyond the bivariate pair.
    Expand this list deliberately, one edge at a time.
    """
    return [
        FlagshipEdge(
            source="inflation",
            target="policy",
            adjustment_set=("growth", "labor"),
            rationale="Taylor-rule style reaction function: CB responds to inflation"
            " conditional on slack.",
        ),
        FlagshipEdge(
            source="policy",
            target="growth",
            adjustment_set=("supply", "positioning"),
            rationale="Monetary transmission to aggregate demand, controlling for"
            " Treasury supply and positioning shocks.",
        ),
        FlagshipEdge(
            source="policy",
            target="positioning",
            adjustment_set=("growth",),
            rationale="Policy change -> flows/positioning, holding real activity fixed.",
        ),
        FlagshipEdge(
            source="labor",
            target="inflation",
            adjustment_set=("growth",),
            rationale="Wage-price channel conditional on activity.",
        ),
        FlagshipEdge(
            source="growth",
            target="labor",
            adjustment_set=(),
            rationale="Okun-style growth-to-hiring pass-through.",
        ),
    ]
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_evaluation.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/flagship.py \
        core/sophia_episto/tests/test_causal/test_evaluation.py
git commit -m "feat: flagship edge registry with defensible adjustment sets"
```

---

### Task 16: DoWhy refutation runner

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/evaluation.py`
- Modify: `core/sophia_episto/tests/test_causal/test_evaluation.py`

- [ ] **Step 1: Write the failing test**

Append to `test_evaluation.py`:

```python
from sophia_episto.causal.evaluation import RefutationResult, run_flagship_refutations
from sophia_episto.causal.flagship import FlagshipEdge


def test_run_flagship_refutations_returns_pass_fail_map():
    rng = np.random.default_rng(0)
    n = 300
    growth = rng.standard_normal(n)
    positioning_noise = rng.standard_normal(n)
    policy = 0.5 * growth + 0.5 * rng.standard_normal(n)
    positioning = 0.7 * policy + 0.3 * positioning_noise

    data = {
        "growth": growth.tolist(),
        "policy": policy.tolist(),
        "positioning": positioning.tolist(),
    }

    edges = [
        FlagshipEdge(
            source="policy",
            target="positioning",
            adjustment_set=("growth",),
            rationale="test",
        )
    ]

    results = run_flagship_refutations(data, edges)
    assert ("policy", "positioning") in results
    r = results[("policy", "positioning")]
    assert isinstance(r, RefutationResult)
    # At least one refutation must have been attempted.
    assert r.tests
    for status in r.tests.values():
        assert status in {"pass", "fail", "error"}
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_evaluation.py::test_run_flagship_refutations_returns_pass_fail_map -x
```
Expected: ImportError.

- [ ] **Step 3: Implement `run_flagship_refutations`**

Append to `evaluation.py`:

```python
import logging
from dataclasses import dataclass as _dc, field as _field

logger = logging.getLogger("sophia_episto.causal.evaluation")


@_dc
class RefutationResult:
    source: str
    target: str
    estimate: float | None = None
    tests: dict[str, str] = _field(default_factory=dict)
    notes: str = ""


def run_flagship_refutations(
    data: dict[str, list[float]],
    flagship_edges: list,  # list[FlagshipEdge] — avoiding circular import
    tolerance: float = 0.25,
) -> dict[tuple[str, str], RefutationResult]:
    """Run DoWhy linear_regression estimation + refutation on flagship edges.

    For each edge, builds a minimal DAG (source -> target with adjustment_set
    as parents of target and source), estimates the effect by backdoor
    linear_regression, and runs three refutation tests:
    - `placebo_treatment`: shuffled treatment should yield ~0 estimate.
    - `random_common_cause`: adding a random confounder should not change
      the estimate meaningfully.
    - `data_subset`: refit on random 70% sample; estimate should be stable.

    A test `passes` when the new estimate is within `tolerance` (relative)
    of the original, except for placebo which passes when |new| <= tolerance
    in absolute terms.
    """
    import pandas as pd

    try:
        from dowhy import CausalModel
    except ImportError:
        logger.warning("dowhy not installed; refutation harness disabled")
        return {}

    results: dict[tuple[str, str], RefutationResult] = {}

    for edge in flagship_edges:
        src, tgt = edge.source, edge.target
        if src not in data or tgt not in data:
            continue
        adjusts = [c for c in edge.adjustment_set if c in data]
        cols = [src, tgt] + adjusts
        df = pd.DataFrame({c: data[c] for c in cols}).dropna()

        if len(df) < 30:
            results[(src, tgt)] = RefutationResult(
                source=src, target=tgt, notes="insufficient rows after align"
            )
            continue

        try:
            # Use common_causes= rather than a hand-built graph string. For
            # flagship edges every adjustment variable is, by construction, a
            # common cause of (src, tgt) — so this is semantically equivalent
            # and eliminates the GML parser as a failure surface.
            model = CausalModel(
                data=df, treatment=src, outcome=tgt, common_causes=adjusts
            )
            identified = model.identify_effect(proceed_when_unidentifiable=True)
            estimate = model.estimate_effect(
                identified,
                method_name="backdoor.linear_regression",
                test_significance=False,
            )
            est_value = float(estimate.value)
        except Exception as exc:
            logger.debug("dowhy estimation failed for %s->%s: %s", src, tgt, exc)
            results[(src, tgt)] = RefutationResult(
                source=src, target=tgt, notes=f"estimation_error: {exc}"
            )
            continue

        tests: dict[str, str] = {}

        def _status(new_value: float, *, placebo: bool = False) -> str:
            if placebo:
                return "pass" if abs(new_value) <= tolerance else "fail"
            if est_value == 0:
                return "pass" if abs(new_value) <= tolerance else "fail"
            rel = abs(new_value - est_value) / abs(est_value)
            return "pass" if rel <= tolerance else "fail"

        for name, method in (
            ("placebo_treatment", "placebo_treatment_refuter"),
            ("random_common_cause", "random_common_cause"),
            ("data_subset", "data_subset_refuter"),
        ):
            try:
                ref = model.refute_estimate(
                    identified, estimate, method_name=method
                )
                new_val = float(ref.new_effect)
                tests[name] = _status(new_val, placebo=(name == "placebo_treatment"))
            except Exception as exc:
                logger.debug("refutation %s failed for %s->%s: %s", name, src, tgt, exc)
                tests[name] = "error"

        results[(src, tgt)] = RefutationResult(
            source=src, target=tgt, estimate=est_value, tests=tests
        )

    return results
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_evaluation.py -x
```
Expected: PASS. (DoWhy is slow; allow up to ~30s.)

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/evaluation.py \
        core/sophia_episto/tests/test_causal/test_evaluation.py
git commit -m "feat: DoWhy-based flagship refutation runner (placebo, rcc, subset)"
```

---

### Task 17: Write refutation results back onto edges

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/evaluation.py`
- Modify: `core/sophia_episto/tests/test_causal/test_evaluation.py`

- [ ] **Step 1: Write the failing test**

Append to `test_evaluation.py`:

```python
from sophia_episto.causal.evaluation import apply_refutations_to_graph


def test_apply_refutations_to_graph_writes_results():
    g = CausalGraph()
    g.add_edge(CausalEdge(source="policy", target="positioning", probability=0.5))
    results = {
        ("policy", "positioning"): RefutationResult(
            source="policy",
            target="positioning",
            estimate=0.42,
            tests={
                "placebo_treatment": "pass",
                "random_common_cause": "pass",
                "data_subset": "fail",
            },
        )
    }
    apply_refutations_to_graph(g, results)
    e = g.get_edge("policy", "positioning")
    assert e.refutation_results["placebo_treatment"] == "pass"
    assert e.refutation_results["data_subset"] == "fail"
    assert e.last_evaluated is not None
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_evaluation.py::test_apply_refutations_to_graph_writes_results -x
```
Expected: ImportError.

- [ ] **Step 3: Implement `apply_refutations_to_graph`**

Append to `evaluation.py`:

```python
def apply_refutations_to_graph(
    graph: CausalGraph,
    results: dict[tuple[str, str], RefutationResult],
) -> None:
    now = _datetime.now(UTC)
    for (src, tgt), res in results.items():
        edge = graph.get_edge(src, tgt)
        if edge is None:
            continue
        edge.refutation_results = dict(res.tests)
        edge.last_evaluated = now
    graph.updated_at = now
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_evaluation.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/evaluation.py \
        core/sophia_episto/tests/test_causal/test_evaluation.py
git commit -m "feat: write refutation pass/fail onto flagship edges"
```

---

## Phase 5 — Integration and reporting

### Task 18: Evaluation report summarizer

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/evaluation.py`
- Modify: `core/sophia_episto/tests/test_causal/test_evaluation.py`

- [ ] **Step 1: Write the failing test**

Append to `test_evaluation.py`:

```python
from sophia_episto.causal.evaluation import summarize_evaluation


def test_summarize_evaluation_produces_daily_report_shape():
    stability = BootstrapStabilityReport(
        n_resamples=100,
        block_size=20,
        edge_frequency={("x", "y"): 0.9, ("x", "z"): 0.3},
        edges_stable=[("x", "y")],
        edges_unstable=[("x", "z")],
    )
    refs = {
        ("policy", "growth"): RefutationResult(
            source="policy",
            target="growth",
            estimate=0.4,
            tests={"placebo_treatment": "pass", "random_common_cause": "fail"},
        )
    }
    report = summarize_evaluation(stability, refs)
    assert report["n_edges_stable"] == 1
    assert report["n_edges_unstable"] == 1
    assert "policy->growth" in report["flagship_refutations"]
    assert report["flagship_refutations"]["policy->growth"]["placebo_treatment"] == "pass"
    assert "timestamp" in report
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_evaluation.py::test_summarize_evaluation_produces_daily_report_shape -x
```

- [ ] **Step 3: Implement `summarize_evaluation`**

Append to `evaluation.py`:

```python
def summarize_evaluation(
    stability: BootstrapStabilityReport,
    refutations: dict[tuple[str, str], RefutationResult],
) -> dict:
    return {
        "timestamp": _datetime.now(UTC).isoformat(),
        "n_edges_stable": len(stability.edges_stable),
        "n_edges_unstable": len(stability.edges_unstable),
        "stability_threshold": 0.6,
        "edge_frequencies": {
            f"{s}->{t}": round(f, 3)
            for (s, t), f in sorted(stability.edge_frequency.items())
        },
        "flagship_refutations": {
            f"{s}->{t}": {
                "estimate": r.estimate,
                **r.tests,
                **({"notes": r.notes} if r.notes else {}),
            }
            for (s, t), r in sorted(refutations.items())
        },
    }
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_evaluation.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/evaluation.py \
        core/sophia_episto/tests/test_causal/test_evaluation.py
git commit -m "feat: evaluation summarizer (daily green/red report shape)"
```

---

### Task 19: `CausalWorldModelService.run_evaluation` + integrate into daily batch

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal_service.py`
- Modify: `core/sophia_episto/tests/test_causal/test_service.py`

- [ ] **Step 1: Write the failing test**

Append to `test_service.py`:

```python
def test_service_run_evaluation_populates_edge_metadata(isolated_save_graph):
    rng = np.random.default_rng(0)
    n = 200
    x = rng.standard_normal(n)
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = 0.8 * x[t - 1] + 0.1 * rng.standard_normal()

    svc = CausalWorldModelService(graph=CausalGraph())
    svc.graph.add_node("x")
    svc.graph.add_node("y")
    svc.ingest_data("x", x.tolist())
    svc.ingest_data("y", y.tolist())

    # Seed the edge so apply_stability has something to write onto.
    from sophia_episto.causal.edge import CausalEdge
    svc.graph.add_edge(CausalEdge(source="x", target="y", probability=0.5))

    report = svc.run_evaluation(n_resamples=20, block_size=20, run_refutations=False)
    assert "timestamp" in report
    edge = svc.graph.get_edge("x", "y")
    assert edge.stability_score is not None
    assert edge.last_evaluated is not None


def test_daily_batch_emits_evaluation_when_enabled(isolated_save_graph):
    svc = CausalWorldModelService(graph=CausalGraph())
    result = svc.run_daily_batch(run_evaluation=False)
    assert "evaluation" not in result

    result = svc.run_daily_batch(run_evaluation=True)
    # With no data, evaluation returns an empty-shape report but the key is present.
    assert "evaluation" in result
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_service.py -x
```
Expected: FAIL — `run_evaluation` method missing.

- [ ] **Step 3: Add `run_evaluation` + wire into `run_daily_batch`**

In `causal_service.py`, add imports at top of the file:

```python
from sophia_episto.causal.evaluation import (
    apply_refutations_to_graph,
    apply_stability_to_graph,
    run_bootstrap_stability,
    run_flagship_refutations,
    summarize_evaluation,
)
from sophia_episto.causal.flagship import flagship_edges
from sophia_episto.causal.preprocessing import prepare_for_discovery
```

Add a method (inside `CausalWorldModelService`):

```python
    def run_evaluation(
        self,
        n_resamples: int = 100,
        block_size: int = 20,
        run_refutations: bool = True,
    ) -> dict[str, Any]:
        """Run the Pearl-lite evaluation harness.

        Returns the summarized report dict and writes per-edge stability /
        refutation metadata onto the graph in place.
        """
        if self.graph is None:
            self.initialize()

        if not self._data:
            logger.info("run_evaluation: no data ingested; returning empty report")
            from sophia_episto.causal.evaluation import BootstrapStabilityReport

            return summarize_evaluation(
                BootstrapStabilityReport(n_resamples=0, block_size=0), {}
            )

        variables = list(self._data.keys())
        stability = run_bootstrap_stability(
            data=self._data,
            variables=variables,
            n_resamples=n_resamples,
            block_size=block_size,
        )
        apply_stability_to_graph(self.graph, stability)

        refutations: dict = {}
        if run_refutations:
            prepared, _ = prepare_for_discovery(self._data)
            refutations = run_flagship_refutations(prepared, flagship_edges())
            apply_refutations_to_graph(self.graph, refutations)

        report = summarize_evaluation(stability, refutations)
        save_graph(self.graph)
        return report
```

Update `run_daily_batch` signature to accept `run_evaluation: bool = False`:

```python
    def run_daily_batch(self, run_evaluation: bool = False) -> dict[str, Any]:
```

At the end of `run_daily_batch`, just before `return results`, add:

```python
        if run_evaluation:
            results["evaluation"] = self.run_evaluation()
```

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/test_service.py -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal_service.py \
        core/sophia_episto/tests/test_causal/test_service.py
git commit -m "feat: CausalWorldModelService.run_evaluation + daily_batch hook"
```

---

### Task 20: Expose evaluation state in graph-state + Prima adapter

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal_service.py` (`get_graph_state`)
- Modify: `agents/sophia_prima/src/sophia/episto_adapter.py`
- Test: extend `core/sophia_episto/tests/test_causal/test_service.py`

- [ ] **Step 1: Write the failing test**

Append to `test_service.py`:

```python
def test_get_graph_state_includes_evaluation_metadata():
    from sophia_episto.causal.edge import CausalEdge
    g = CausalGraph()
    g.add_edge(CausalEdge(
        source="a", target="b",
        stability_score=0.82,
        refutation_results={"placebo_treatment": "pass"},
    ))
    svc = CausalWorldModelService(graph=g)
    state = svc.get_graph_state()
    edge = next(e for e in state["edges"] if e["source"] == "a")
    assert edge["stability_score"] == 0.82
    assert edge["refutation_results"]["placebo_treatment"] == "pass"
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_causal/test_service.py::test_get_graph_state_includes_evaluation_metadata -x
```

- [ ] **Step 3: Extend `get_graph_state`**

In `causal_service.py`, within `get_graph_state`, update the edges dict comprehension:

```python
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "probability": e.probability,
                    "confidence": e.confidence,
                    "strength": e.strength,
                    "mechanism": e.mechanism,
                    "stability_score": e.stability_score,
                    "refutation_results": e.refutation_results,
                    "last_evaluated": e.last_evaluated.isoformat() if e.last_evaluated else None,
                }
                for e in self.graph.edges
            ],
```

In `agents/sophia_prima/src/sophia/episto_adapter.py`, no change needed — `get_causal_graph_state` already passes through the dict.

- [ ] **Step 4: Run the tests**

```
pytest tests/test_causal/ -x
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal_service.py \
        core/sophia_episto/tests/test_causal/test_service.py
git commit -m "feat: surface evaluation metadata in graph state"
```

---

### Task 21: Full regression run + update `__init__.py` exports

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/causal/__init__.py`

- [ ] **Step 1: Add new public symbols to the causal package `__init__.py`**

Append to `core/sophia_episto/src/sophia_episto/causal/__init__.py`:

```python
from sophia_episto.causal.effect_size import (
    partial_r_squared,
    standardized_beta,
    strength_from_lagged_regression,
)
from sophia_episto.causal.evaluation import (
    BootstrapStabilityReport,
    RefutationResult,
    apply_refutations_to_graph,
    apply_stability_to_graph,
    run_bootstrap_stability,
    run_flagship_refutations,
    summarize_evaluation,
)
from sophia_episto.causal.flagship import FlagshipEdge, flagship_edges
from sophia_episto.causal.preprocessing import (
    PreprocessingReport,
    StationarityReport,
    is_stationary,
    prepare_for_discovery,
)
```

And extend `__all__`:

```python
__all__ = [
    "BootstrapStabilityReport",
    "CausalDiscovery",
    "CausalEdge",
    "CausalGraph",
    "CausalInference",
    "DiscoveredEdge",
    "FlagshipEdge",
    "InferenceResult",
    "PreprocessingReport",
    "RefutationResult",
    "StationarityReport",
    "apply_refutations_to_graph",
    "apply_stability_to_graph",
    "create_initial_graph",
    "expert_priors",
    "flagship_edges",
    "is_stationary",
    "load_graph",
    "partial_r_squared",
    "prepare_for_discovery",
    "query_causal_effect",
    "rank_candidates",
    "run_bootstrap_stability",
    "run_flagship_refutations",
    "save_graph",
    "standardized_beta",
    "strength_from_lagged_regression",
    "summarize_evaluation",
]
```

- [ ] **Step 2: Run the full test suite**

```
cd core/sophia_episto && pytest -x
cd ../../services/sophia_arithmos && pytest -x
```
Expected: PASS.

- [ ] **Step 3: Verify no Pearl/do-calculus overclaims remain**

```
grep -rn -iE "do-calculus|do_calculus|pearl'?s? causal|forward_simulate" \
  core/sophia_episto/src agents/sophia_prima/src services/sophia_arithmos/src
```
Expected: no matches except in docstrings that explicitly disclaim ("NOT Pearl", "NOT a Pearl-style").

- [ ] **Step 4: Commit**

```bash
git add core/sophia_episto/src/sophia_episto/causal/__init__.py
git commit -m "chore: export evaluation, preprocessing, flagship public API"
```

---

## Self-Review Notes

- **Spec coverage:** Every requirement from the design conversation is represented:
  - Unblock (Tasks 1–4): syntax error, method name, Observation schema, smoke test.
  - Honesty pass (Task 5): Pearl overclaims, `forward_simulate` rename.
  - Foundation correctness (Tasks 6–10): stationarity, effect size, `1−p` replacement, FDR, atomic writes.
  - Pearl-lite evaluation harness (Tasks 11–18): edge metadata, bootstrap stability, DoWhy refutation on flagship edges, summarizer.
  - Integration/reporting (Tasks 19–21): service method, daily-batch hook, graph-state surfacing, package exports.
- **Deferred explicitly:** Regime-conditional activation, series-id ↔ concept mapping, dashboard UI, full backdoor-set discovery. Noted in scope boundaries.
- **Risk flag for executing engineer:** DoWhy + pandas add ~100MB to the env. Task 14 should be run on the machine you intend to schedule batches on. DoWhy tests may be flaky under low sample sizes; if Task 16's test is intermittently failing, raise `n` to 500 in the test rather than loosening `tolerance`.
- **Estimated effort:** 5–8 focused days solo. Phases 0–2 can be one sitting if uninterrupted (~day 1); Phase 3 ~day 2; Phases 4–5 ~days 3–5 (DoWhy tuning is the unknown).
