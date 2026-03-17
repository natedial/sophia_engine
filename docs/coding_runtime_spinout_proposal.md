# Coding Runtime Spinout Proposal

**Document Version:** 0.1
**Date:** 2026-03-16
**Status:** Draft - Recommended Direction

---

## Executive Summary

This proposal recommends spinning out Sophia's coding capability into a **standalone coding runtime** rather than a standalone general-purpose agent.

The distinction matters:

- A standalone coding **agent** would mostly package prompt logic around Codex or Claude Code.
- A standalone coding **runtime** would own the harder, more defensible pieces: bounded execution, workspace policy, backend adapters, run traces, artifacts, verification, and evaluation.

The current codebase already has the early seams needed for this approach:

- `sophia_prima` is explicitly the conversational/surface layer.
- delegated coding already sits behind a backend abstraction with structured output.
- run traces and artifacts already exist in the gateway runtime.
- domain tools are already separated behind `sophia_pylon`.

The recommendation is to first extract this capability into a first-class in-monorepo runtime service, then split it into a standalone repo/product only after the API, operational model, and evaluation harness stabilize.

---

## 1. Current State

### 1.1 What Already Exists

The current architecture already separates several concerns in the right direction:

- `sophia_prima` is the user-facing conversational layer and gateway.
- `sophia_pylon` is the domain tool and backend integration layer.
- delegated coding is optional and backend-pluggable.

Relevant codebase signals:

- `agents/sophia_prima/README.md` defines `sophia_prima` as the conversational layer and already exposes an optional `coding_worker`.
- `agents/sophia_prima/src/sophia/coding_workers/base.py` defines a reusable execution contract with structured outputs, bounded workspace prep, and filesystem policy checks.
- `agents/sophia_prima/src/sophia/coding_workers/codex.py` implements a Codex backend behind that contract.
- `agents/sophia_prima/src/sophia/subagents.py` already treats coding as a delegable subagent responsibility.
- `agents/sophia_prima/src/sophia/gateway/run_store.py` already persists runs, events, and artifacts.
- `services/sophia_pylon/README.md` cleanly separates domain-tool execution from the agent surface.

### 1.2 What Is Missing

What exists today is a good kernel, but not yet a standalone product boundary.

Missing or underdeveloped pieces:

- explicit run API for coding tasks
- first-class event model for coding run lifecycle
- verification recipes and structured pass/fail outcomes
- reusable task blueprints and context assembly rules
- evaluation corpus and regression tracking
- isolated execution beyond a bounded local workspace
- ergonomics for clients other than `sophia_prima`

### 1.3 The Core Architectural Question

The real question is not whether to "spin out coding."

The real question is:

> Should we package the current coding worker as a product, or build a runtime around coding work that multiple clients can depend on?

This proposal recommends the latter.

---

## 2. Recommendation

### 2.1 Recommended Direction

Create a standalone runtime product boundary for coding execution. Suggested internal name: **`sophia_forge`**.

`sophia_forge` should own:

- run submission and lifecycle
- workspace and permission policy
- backend adapters for Codex, Claude Code, and future backends
- prompt/context assembly for coding tasks
- structured artifacts and traces
- verification execution and result capture
- evaluation harness and benchmark corpus

`sophia_forge` should **not** own:

- general chat UX
- long-lived conversational memory
- Telegram or other channel adapters
- domain research tools and market-data workflows
- broad "personal assistant" behavior

### 2.2 Why This Boundary Is Better

This direction creates a more defensible system because the value moves away from "which model did we call" and toward:

- safe and bounded execution
- predictable task intake
- repeatable verification
- consistent artifacts for review
- observability into failure modes
- backend portability

That is much closer to the operating model described in Stripe's Minions posts, where the product value comes from the managed system around the model, not the prompt alone.

---

## 3. Proposed Product Boundary

### 3.1 `sophia_prima` Responsibilities

Keep `sophia_prima` focused on:

- user interaction
- intent understanding
- deciding when coding work is needed
- collecting missing context from the user
- presenting results, risks, and follow-ups

In this model, `sophia_prima` becomes a client of the coding runtime rather than the home of coding execution.

### 3.2 `sophia_forge` Responsibilities

`sophia_forge` should own the full lifecycle of a coding run:

1. Accept task input and execution policy.
2. Materialize or attach to a workspace.
3. Assemble coding-specific context and constraints.
4. Invoke the configured backend.
5. Run targeted verification.
6. Persist events, artifacts, and summaries.
7. Return a structured result to the caller.

### 3.3 `sophia_pylon` Responsibilities

`sophia_pylon` should remain the domain tool fabric.

Coding tasks may use or extend systems that also surface through `pylon`, but `pylon` should not absorb coding-runtime concerns. The current separation is good and should be preserved.

---

## 4. Target Architecture

### 4.1 High-Level Shape

```text
┌─────────────────────────────────────────────────────────────┐
│                         Clients                              │
│  sophia_prima  |  CLI  |  CI hooks  |  future UI/API users  │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                      sophia_forge                           │
│                                                             │
│  Run API        Workspace mgr     Backend adapters          │
│  Event stream   Context builder   Codex / Claude / future   │
│  Artifact store Verification      Eval harness              │
│                                                             │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Execution Environments                   │
│   local workspace   git worktree   container   remote box   │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 API Shape

Initial API should be intentionally small:

- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/events`
- `GET /runs/{run_id}/artifacts`
- `POST /runs/{run_id}/cancel`

Run request fields should include:

- task text
- repo/workspace target
- writable scope
- backend selection
- timeout budget
- verification policy
- metadata about initiator and source surface

Run result fields should include:

- status
- concise summary
- changed files
- verification results
- follow-ups
- artifact references
- failure reason when not completed

### 4.3 Artifact Model

Artifacts should become first-class objects, not just backend leftovers.

Minimum artifact types:

- task specification
- assembled prompt/context package
- backend final message
- patch or changed-file manifest
- verification logs
- human review summary

The existing gateway run store provides a useful starting pattern, but the artifact model should move from gateway-specific storage toward runtime-specific contracts.

---

## 5. Proposed Package and Service Shape

### 5.1 Phase 1 Monorepo Structure

Recommended initial structure:

- `services/sophia_forge/`
  - runtime API, worker orchestration, backend adapters, verification runner
- `shared/sophia_forge_protocol/`
  - request/response schemas, event types, artifact models
- `agents/sophia_prima/`
  - client integration only

### 5.2 Why This Structure

This gives a clean internal boundary before a repo split:

- `shared/` holds durable contracts.
- `services/` holds runtime behavior and operational concerns.
- `agents/` remains a consumer.

That is a better forcing function than immediately creating a new repository while the API is still fluid.

### 5.3 Naming

Suggested working name: `sophia_forge`

Rationale:

- distinct from `prima` and `pylon`
- reads as a build/execution system, not a chat persona
- flexible enough to cover coding runs, verification, and evaluation

If you want a more neutral name for later externalization, the runtime can expose a product-facing label later while keeping `sophia_forge` as the internal codename.

---

## 6. Migration Plan

### Phase 0: Stabilize the Existing Kernel

Goal: make the current coding worker implementation extraction-ready without changing behavior.

Actions:

- define explicit `RunRequest`, `RunEvent`, `RunArtifact`, and `RunResult` models
- move backend-agnostic result contracts out of `sophia_prima`
- isolate prompt assembly from gateway-specific code paths
- standardize artifact output directories and naming

Exit criteria:

- coding run contract is no longer coupled to `sophia_prima` internals
- Codex and Claude Code both implement the same stable runtime interface

### Phase 1: Create `services/sophia_forge`

Goal: move coding execution behind a local service boundary inside the monorepo.

Actions:

- create the runtime service with a small HTTP API
- port current coding worker backends into the new service
- move run persistence from gateway-oriented tables to forge-oriented run models
- update `sophia_prima` to submit coding jobs instead of executing them directly

Exit criteria:

- `sophia_prima` can trigger coding runs through the service
- local development works without changing user-facing behavior

### Phase 2: Add Verification and Evals

Goal: make the runtime operationally trustworthy.

Actions:

- add verification recipes by task type
- capture structured pass/fail outcomes
- create an eval corpus from real coding tasks
- track success rate, retry rate, and common failure classes

Exit criteria:

- you can compare backends and prompt changes against a stable benchmark
- verification results are visible in every completed run

### Phase 3: Add Stronger Isolation

Goal: improve safety and reproducibility.

Actions:

- support git worktree-based execution
- support per-run ephemeral environments
- define secret injection policy
- add cleanup and retention rules for workspaces and artifacts

Exit criteria:

- runs are reproducible and do not depend on a shared mutable workspace

### Phase 4: Externalize

Goal: split repo or product boundary only after the runtime is mature enough to stand alone.

Actions:

- publish a stable client SDK
- move service deployment and operations into its own lane
- document supported backends and execution guarantees
- decide whether external users are in scope or whether this remains an internal platform product

Exit criteria:

- at least 2-3 real clients depend on the runtime
- API churn has materially slowed
- runtime metrics support independent operation

---

## 7. Spin-Out Gates

Do not split this into a standalone repo or company-level tool until most of the following are true:

- there is a stable run contract used by multiple clients
- verification is first-class rather than best-effort
- there is an eval suite with regression tracking
- execution is isolated enough to be operationally safe
- artifacts and traces are useful for debugging failed runs
- the system is still valuable if the underlying model backend changes

If those are not true yet, a repo split is likely to create coordination overhead without creating a real product advantage.

---

## 8. Risks and Mitigations

### Risk 1: Thin Wrapper Product

Risk:
- the spin-out becomes a prompt wrapper around Codex or Claude Code

Mitigation:
- invest early in runtime contracts, verification, evals, and artifacts

### Risk 2: Premature Repo Split

Risk:
- cross-repo churn slows development while the interface is still changing

Mitigation:
- do the extraction inside the monorepo first

### Risk 3: Boundary Confusion with `sophia_prima`

Risk:
- chat behaviors, memory, and coding execution remain mixed together

Mitigation:
- force all new coding functionality through the runtime API once Phase 1 starts

### Risk 4: Weak Operational Feedback

Risk:
- failures are hard to diagnose, making iteration slow

Mitigation:
- standardize event streams, artifact capture, and failure taxonomy

---

## 9. Immediate Next Steps

Recommended next actions:

1. Approve the boundary: standalone coding runtime, not standalone general agent.
2. Create `shared/sophia_forge_protocol` contracts for runs, events, artifacts, and results.
3. Stand up `services/sophia_forge` as an in-monorepo runtime service.
4. Switch `sophia_prima` from direct coding-worker execution to client mode.
5. Build the first eval set from real coding tasks before any repo split.

---

## 10. Bottom Line

You should spin out the coding capability, but only as a **runtime platform** with clear operational ownership.

If you spin out the current coding worker abstraction by itself, you will mostly be packaging a dependency.

If you spin out the managed system around coding work, you have the beginnings of a real product.

---

## References

- Stripe, "Minions: Stripe's one-shot, end-to-end coding agents"
  https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents
- Stripe, "Minions: Stripe's one-shot, end-to-end coding agents, Part 2"
  https://stripe.dev/blog/minions-stripes-one-shot-end-to-end-coding-agents-part-2
