# Causal World Model for Economic Data

**Created**: 2026-04-15  
**Status**: Draft for Review (Updated per feedback)

---

## Overview

Build an autonomous causal world model that enables:
- Inferring effects given causes
- Distinguishing causal from correlated relationships
- Probabilistic inference with uncertainty quantification
- Higher agency: proactive hypothesis generation and model execution

**Starting scope**: G3 central banks (Fed, ECB, BOJ)  
**Execution model**: Daily scheduled batch (to control compute costs) - default 5 PM ET (post-US market close)  
**Review interface**: Sophia Prima conversations + dashboard

---

## Architecture Components

### 1. Entity/Actor System

`core/sophia_episto/src/sophia_episto/entities/`

| File | Description |
|------|-------------|
| `__init__.py` | EconomicAgent base class, actor types |
| `central_bank.py` | CentralBank subtype: mandate, policy_function, meeting_schedule |
| `market.py` | Market entity: asset_classes, current state |

**Entity Types**:
- `EconomicAgent` (base): id, name, type, properties
- `CentralBank`: Fed, ECB, BOJ, etc.
- `Corporation`: with sector, size
- `Government`: fiscal authority
- `Market`: asset class representation
- `Investor`: maps to existing `positioning` concept

**Relationships**:
- Actor → Concept: Fed → influences → policy (via ActorConceptEdge)
- Actor → Actor: Treasury → issues_to → Market (via ActorActorEdge)

### 2. Probabilistic Causal Graph

`core/sophia_episto/src/sophia_episto/causal/`

| File | Description |
|------|-------------|
| `graph.py` | CausalGraph with nodes, edges, posteriors |
| `edge.py` | CausalEdge: probability, confidence, strength, mechanism, conditions |
| `inference.py` | Bayesian inference, do-calculus, intervention reasoning |
| `discovery.py` | Granger causality, causal-learn PC, regime-aware detection |

**CausalEdge Schema**:
```python
{
    "source": "node_id",
    "target": "node_id", 
    "relationship": Optional[Relationship],  # None for data-discovered edges
    "probability": float,             # P(effect | cause)
    "confidence": float,              # Expert prior confidence
    "strength": float,               # Empirical strength from data
    "mechanism": str,               # Transmission channel description
    "conditions": dict,             # Regime-dependent modifiers
    "regime_dependent": bool
}
```

**Migration Strategy**: Relationship remains frozen as semantic skeleton. CausalEdge is independent type that references Relationship by (source_concept, target_concept) key, not inheritance.

### 3. Hypothesis Management

`core/sophia_episto/src/sophia_episto/hypothesis/`

| File | Description |
|------|-------------|
| `__init__.py` | Hypothesis type, lifecycle management |
| `generator.py` | Proactive hypothesis from patterns + literature |

**Hypothesis Lifecycle**: PROPOSED → TESTING → VALIDATED/REJECTED

### 4. Scheduled Reasoning Loop

**Daily Execution** (5 PM ET):
1. Ingest new data from Scrivener
2. Run causal discovery (Granger causality)
3. Update Bayesian posteriors
4. Generate new hypotheses
5. Trigger Oikonomia model runs for testing
6. Push results to dashboard + Sophia Prima context

### 5. Persistence Layer

**Decision**: Serialize CausalGraph to JSON in `data/causal_graph/` (repo root)
- Graph state (nodes, edges, posteriors) saved as JSON after each run
- Prior/posterior history retained for analysis
- Simplest approach; repo root (not under episto package) since it's shared mutable state

---

## Implementation Phases

### Phase 1: Foundation (Weeks 1-2)

- [ ] Define EconomicAgent base class
- [ ] Implement CentralBank subtype (Fed, ECB, BOJ) with properties
- [ ] Create ActorConceptEdge type (Actor → Concept references)
- [ ] Create ActorActorEdge type (Actor → Actor relationships)
- [ ] Define CausalEdge as independent type referencing Relationship
- [ ] Set up persistence layer: `data/causal_graph/` JSON serialization
- [ ] Define expert priors for G3 central bank relationships

### Phase 2: Inference Engine (Weeks 2-3)

- [ ] Implement CausalGraph with belief propagation
- [ ] Support do-calculus: `do(X=x)` queries
- [ ] Intervention reasoning: "what if Fed raises 25bp"
- [ ] Counterfactual reasoning
- [ ] Full posterior distributions (not point estimates)

### Phase 3: Data-Driven Discovery (Weeks 3-4)

**Prerequisites**:
- [ ] Add `GrangerCausality` Computation to Arithmos (`services/sophia_arithmos/src/sophia_arithmos/computations/causality.py`)
  - Wrap `statsmodels.tsa.vector_ar.var_model.VAR`
  - Support test for Granger-causality between pairs of series

- [ ] Install `causal-learn` library for PC algorithm

**Tasks**:
- [ ] Granger causality testing via Arithmos GrangerCausality
- [ ] PC algorithm via causal-learn for structure learning
- [ ] Regime-aware relationship detection
- [ ] Output candidate edges ranked by evidence

### Phase 4: Autonomous Agency (Weeks 4-5)

**Prerequisites**:
- [ ] Add `TriggerType.HYPOTHESIS` to Oikonomia (`services/sophia_oikonomia/src/sophia_oikonomia/core/types.py`)
  - Update `_is_plannable` / `_match_trigger` logic

**Tasks**:
- [ ] Hypothesis generation from data patterns
- [ ] Integration with Tholos for literature retrieval
- [ ] Hypothesis lifecycle management
- [ ] Trigger Oikonomia model runs from hypotheses via HYPOTHESIS trigger

### Phase 5: Integration (Weeks 5-6)

**Prerequisites**:
- [ ] Add CausalGraph as input to PlaybookPlanner (via planner.py integration point)

**Tasks**:
- [ ] Wire into Sophia Prima: causal queries, "why" explanations
- [ ] Dashboard: visualize causal graph, confidence intervals
- [ ] Scheduled job setup (daily 5 PM ET execution)

---

## Data Flow

```
[Scrivener data] → [Arithmos (correlations, regressions, Granger)]
                      ↓
[Tholos (literature)] → [Causal Discovery] → [Candidate edges]
                              ↓
                    [Expert review] → [Prior update]
                              ↓
                    [Bayesian Graph] ← [Hypothesis Engine]
                              ↓
[Oikonomia models] ← [Intervention reasoning]
                              ↓
                    [Dashboard + Sophia Prima]
```

---

## Key Design Decisions

| Decision | Approach |
|----------|----------|
| Graph size | Start with ~20-30 nodes (concepts + G3 actors + key derivatives) |
| Inference | Hybrid: exact for small cliques, approximate (Loopy BP) for full graph |
| Learning cadence | Daily batch discovery, continuous posterior updates |
| Human in loop | All discovered relationships need expert confirmation before auto-use |
| Relationship migration | Keep Relationship frozen; CausalEdge references by key |
| PC algorithm | Use causal-learn library, not custom implementation |
| Persistence | JSON serialization to data/causal_graph/ |
| Schedule | Default 5 PM ET (post-US market close, aligned with Scrivener) |

---

## Existing Foundation (To Extend)

| Component | Location | Notes |
|-----------|----------|-------|
| World Model | `core/sophia_episto/src/sophia_episto/world_model/` | 6 concepts, static relationships |
| Data Pipeline | `services/scrivener/` | FRED, BLS, Treasury ingestion |
| Stats Layer | `services/sophia_arithmos/` | Regression, correlations |
| Model Orchestration | `services/sophia_oikonomia/` | Model lifecycle, triggers |
| Search | `services/sophia_tholos/` | Hybrid lexical + semantic |

---

## Files to Create/Modify

### New Files
- `core/sophia_episto/src/sophia_episto/entities/__init__.py`
- `core/sophia_episto/src/sophia_episto/entities/central_bank.py`
- `core/sophia_episto/src/sophia_episto/entities/market.py`
- `core/sophia_episto/src/sophia_episto/causal/__init__.py`
- `core/sophia_episto/src/sophia_episto/causal/graph.py`
- `core/sophia_episto/src/sophia_episto/causal/edge.py`
- `core/sophia_episto/src/sophia_episto/causal/inference.py`
- `core/sophia_episto/src/sophia_episto/causal/discovery.py`
- `core/sophia_episto/src/sophia_episto/hypothesis/__init__.py`
- `core/sophia_episto/src/sophia_episto/hypothesis/generator.py`
- `services/sophia_arithmos/src/sophia_arithmos/computations/causality.py` (Granger)

### Modified Files
- `core/sophia_episto/src/sophia_episto/world_model/` - integrate new causal system
- `services/sophia_oikonomia/src/sophia_oikonomia/core/types.py` - add HYPOTHESIS trigger
- `services/sophia_arithmos/src/sophia_arithmos/computations/__init__.py` - register Granger
- `agents/sophia_prima/` - integrate CausalGraph into PlaybookPlanner

### Data Directory
- `data/causal_graph/` (repo root) - JSON serialization for graph persistence

---

## Dependencies

| Package | Purpose | Phase |
|---------|---------|-------|
| causal-learn | PC algorithm backend | Phase 3 |
| statsmodels | VAR models for Granger | Phase 3 (already imported) |

---

## Open Questions

1. **Initial scope**: G3 (Fed + ECB + BOJ) - confirmed
2. **Expert review mechanism**: Dashboard + Sophia Prima conversations - confirmed
3. **Scheduled job timing**: Default 5 PM ET - confirmed
