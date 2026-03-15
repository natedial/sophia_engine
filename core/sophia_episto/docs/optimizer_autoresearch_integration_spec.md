# Optimizer and Autoresearch Integration Spec

## Purpose

The econ research system should support offline optimization of planning behavior, lesson usage, source ranking, and policy thresholds without coupling optimization to the live answer path.

This spec reserves an integration path for an `autoresearch`-style loop while keeping production execution controlled and auditable.

Reference approach:

- [karpathy/autoresearch](https://github.com/karpathy/autoresearch)

## High-Level Model

There are two distinct loops:

### Online Loop

Handles user questions in production.

```text
question -> plan -> capability check -> acquisition decision -> analysis -> answer
```

### Offline Optimization Loop

Improves system components using bounded experiments.

```text
eval suite -> propose mutation -> run experiment -> score -> keep/reject
```

The optimization loop must never be required for runtime correctness.

## Optimization Targets

The initial editable surface should be narrow.

Allowed targets:

- playbook prompts and heuristics
- planner strategy configuration
- lesson retrieval policies
- source ranking policies
- acquisition thresholds
- retention policy thresholds
- evaluation configuration

Protected targets:

- gateway runtime behavior
- storage schema
- canonical ingestion code
- source allowlist enforcement
- auth and security policy

## Optimizer Interface

Recommended contract:

```python
class OptimizationAdapter(ABC):
    name: str

    @abstractmethod
    def propose(self, program: OptimizationProgram) -> list[ProposedChange]: ...

    @abstractmethod
    def evaluate(self, changes: list[ProposedChange]) -> ExperimentResult: ...
```

## `AutoresearchAdapter`

The adapter should wrap an `autoresearch`-style loop conceptually, but not embed the repo directly into the online runtime.

Responsibilities:

- build a constrained experiment workspace
- expose a small editable surface
- run eval suites
- return scored diffs and artifacts

Non-responsibilities:

- direct deployment
- direct production writes
- unrestricted codebase edits

## Program Inputs

The optimizer should be driven by an explicit program/config artifact, similar to the role `program.md` plays in `autoresearch`.

Suggested inputs:

- optimization goal
- allowed files/modules
- eval suite
- scoring weights
- budget limits
- stop conditions

Recommended artifact:

```text
src/sophia_episto/optimizer/program.md
```

## Evaluation Harness

Optimization only works if there are measurable outcomes.

Each experiment should run against an eval suite with metrics such as:

- plan quality
- expected indicator coverage
- citation validity
- contradiction handling
- unnecessary acquisition penalty
- latency penalty
- cost penalty

Recommended weighted score:

```text
total_score =
  0.30 * plan_quality +
  0.25 * evidence_coverage +
  0.20 * citation_validity +
  0.15 * acquisition_efficiency +
  0.10 * cost_latency_efficiency
```

## Experiment Artifacts

Every optimization run should persist:

- experiment id
- base version
- proposed changes
- changed files
- metric deltas
- keep/reject decision
- rationale

This should integrate with the existing gateway/run persistence model conceptually, but should remain an `episto` concern for optimizer experiments.

## Safety Rules

- offline only at first
- fixed experiment budget
- fixed editable surface
- no arbitrary external browsing from the optimizer by default
- no canonical data mutations
- no automatic merge/deploy behavior

## Incremental Rollout

### Phase 1

- define optimizer interfaces
- define eval artifact formats
- add `AutoresearchAdapter` stub
- no external optimizer execution yet

### Phase 2

- run optimizer against playbook configs only
- compare against baseline eval suites
- require human review

### Phase 3

- permit limited planner-module edits in a branch/workspace
- still require human review

### Phase 4

- optional semi-automated PR generation for accepted improvements

## Repo Integration Points

### In `sophia_episto`

- `optimizer/base.py`
- `optimizer/autoresearch_adapter.py`
- `evaluation/harness.py`
- `evaluation/metrics.py`

### In `sophia_prima`

No direct optimizer dependency should be required for runtime execution.

`prima` may later surface experiment summaries or choose among versioned playbooks, but it should not run optimization loops inline.

## Open Decisions

- where experiment results are stored
- whether optimizer runs use a local branch or temporary workspace
- whether external `autoresearch` execution is vendored, wrapped, or just mirrored conceptually
- how broad the editable surface becomes over time

## Recommendation

Start with a narrow optimizer scope:

- playbook definitions
- retrieval thresholds
- lesson ranking policies

That is enough to get measurable gains without risking runtime destabilization.
