# Episto Architecture Spec

## Purpose

`sophia_episto` will become the shared planning and economic-reasoning substrate for Sophia.

It should own:

- world-model concepts and relationship primitives
- research plan schemas
- domain playbooks
- methodological lessons
- applicability and regime logic
- evaluation and optimizer interfaces

It should not own:

- channel/runtime orchestration
- direct tool execution
- canonical data writes
- source-specific acquisition code

## Package Boundaries

### `core/sophia_episto`

Owns reusable economic reasoning and planning abstractions.

### `agents/sophia_prima`

Owns runtime supervision, channel handling, subagent orchestration, and session execution.

`prima` consumes plans from `episto` and executes them through `pylon`.

### `services/sophia_pylon`

Owns stable tool contracts to backend services. It should remain unaware of playbook logic.

### `services/scrivener` and future acquisition subsystem

Own canonical structured-data storage, staging storage, validation, provenance, and on-demand acquisition.

### `skills/`

Own authoring and operating workflows that help humans or agents create, audit, and optimize
`episto` assets. Skills should not become the canonical runtime implementation for playbooks,
world-model logic, or typed planning artifacts.

## Architectural Principle

Questions should compile into plans.

Plans should resolve against a capability graph.

Capability gaps should trigger controlled acquisition decisions.

Only after evidence is assembled should synthesis occur.

## Target Module Layout

```text
core/sophia_episto/
├── pyproject.toml
├── README.md
├── docs/
│   ├── episto_architecture_spec.md
│   ├── econ_research_playbook_spec.md
│   └── optimizer_autoresearch_integration_spec.md
└── src/sophia_episto/
    ├── __init__.py
    ├── plan_models.py
    ├── planner.py
    ├── policy.py
    ├── lesson_store.py
    ├── capability.py
    ├── evaluation/
    │   ├── __init__.py
    │   ├── cases.py
    │   ├── metrics.py
    │   └── harness.py
    ├── world_model/
    │   ├── __init__.py
    │   ├── concepts.py
    │   ├── relationships.py
    │   └── regimes.py
    ├── playbooks/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── labor_vs_growth.py
    │   ├── inflation_decomposition.py
    │   ├── fed_reaction_function.py
    │   └── supply_term_premium.py
    └── optimizer/
        ├── __init__.py
        ├── base.py
        └── autoresearch_adapter.py
```

## Core Runtime Flow

```text
user question
-> prima supervisor
-> episto QuestionBrief + ResearchPlan
-> capability resolver
-> local data check
-> acquisition decision on gaps
-> tool execution through pylon
-> analysis result
-> answer synthesis
-> lesson capture
```

## Core Artifacts

### `QuestionBrief`

- normalized user question
- intent class
- answer type
- time horizon
- scope constraints

### `ResearchPlan`

- plan id
- playbook id
- subquestions
- hypotheses
- candidate indicators
- required transforms
- comparison windows
- success criteria

### `EvidencePlan`

- local capability checks
- required datasets
- missing datasets
- validation requirements
- citation requirements

### `CapabilityCheck`

- requested indicator
- local availability
- freshness status
- compatible source options
- acquisition needed flag

### `AcquisitionDecision`

- fetch now / defer / reject
- source candidate
- rationale
- retention target

### `AnalysisResult`

- findings
- contradictions
- caveats
- confidence
- evidence references

### `LessonRecord`

- lesson class
- trigger pattern
- lesson text
- evidence basis
- reuse scope
- expiry/review state

## World Model Requirements

The world model should represent economic concepts independently from any one dataset.

Examples:

- concepts: GDP growth, payroll growth, unemployment, labor force participation, wage pressure
- relations: confirms, weakens, leads, lags, substitutes, caveats, invalidates
- regimes: disinflation, late-cycle slowdown, reacceleration, policy tightening, supply shock

This lets playbooks ask for "labor tightness" or "growth resilience" before mapping to exact series.

## Interface Contracts

The first package-level interfaces should be:

- `PlannerStrategy`
- `Playbook`
- `LessonProvider`
- `CapabilityResolver`
- `AcquisitionPolicy`
- `RetentionPolicy`
- `EvaluationMetric`
- `OptimizationAdapter`

These should be explicit Python interfaces or abstract base classes so they can be swapped for testing and optimization.

## Skills Boundary

Skills are appropriate for:

- playbook authoring workflows
- lesson curation and review workflows
- source adapter onboarding checklists
- evaluation and optimizer operating procedures

Skills are not the right home for:

- canonical playbook definitions used at runtime
- world-model relationships
- typed plan and evidence artifacts
- acquisition and retention policy implementations

Rule of thumb:

- If the asset must be imported, versioned, and tested as runtime behavior, it belongs in `episto`.
- If the asset helps create, review, or improve that runtime behavior, it can live in the skill tree.

This lets the platform use skills as a controlled authoring layer above `episto`, including future
`autoresearch`-style optimization loops, without moving execution-critical logic into prompt-only assets.

## Persistence Guidance

Initial `episto` scope should prefer interfaces over hard persistence dependencies.

Recommended approach:

- `episto` defines store interfaces and in-memory/dev implementations
- `prima` or future services wire concrete persistence backends

This keeps `episto` reusable and easier to test.

## Refactor Plan

### Phase 1: Package Formation

- create real Python package scaffold for `sophia_episto`
- move existing interview framework assets under package ownership
- add initial plan and lesson models

### Phase 2: Planning Core

- implement `QuestionBrief`, `ResearchPlan`, `EvidencePlan`
- add planner interface and first planner implementation
- add first playbook: `labor_vs_growth`

### Phase 3: Runtime Integration

- add `prima -> episto` planning call boundary
- keep execution in `prima`
- keep tools in `pylon`

### Phase 4: Capability and Acquisition Policies

- add capability resolver interfaces
- add acquisition and retention policy interfaces
- integrate with Scrivener and future acquisition service

### Phase 5: Evaluation and Optimization

- add eval case format and harness
- add optimizer interface
- add `AutoresearchAdapter` as offline optimization path

## Non-Goals for Initial Build

- direct autonomous code modification in production
- unrestricted web crawling
- arbitrary self-expanding world-model ontology
- moving all memory from `prima` into `episto`

## Immediate Deliverables

Before broader implementation starts, the repo should gain:

- packaged `episto`
- one working playbook
- one planner
- one eval suite
- one `prima` integration path

That is the minimum slice that proves the package boundary is correct.
