# Forge Long-Running Capabilities Plan

**Document Version:** 0.1
**Date:** 2026-03-19
**Status:** Draft

## Purpose

This document defines a concrete implementation plan for improving `sophia_forge` so it can supervise longer-running coding tasks more effectively.

The target outcome is:

- clients can observe run progress without tight polling loops
- transient backend failures can be retried by the runtime itself
- long tasks can be continued through durable Forge-owned sessions instead of only one-off runs
- callers can steer active work without cancelling and restarting
- resumed work can start from Forge checkpoints instead of replaying full history

This plan is intentionally additive. It extends the current Forge service model rather than replacing it with a full interactive agent runtime.

## Current State

Today Forge already provides strong outer-run supervision:

- run submission and status APIs
- persistent events, artifacts, and verification results
- workspace and environment preparation
- backend dispatch
- eval and retention support

Relevant implementation points:

- `services/sophia_forge/src/sophia_forge/core/scheduler.py`
- `services/sophia_forge/src/sophia_forge/core/runtime.py`
- `services/sophia_forge/src/sophia_forge/api/routes.py`
- `services/sophia_forge/src/sophia_forge/storage/run_store.py`
- `agents/sophia_prima/src/sophia_forge_protocol/`

Current gaps for long-running work:

- progress is persisted, but clients still rely on polling
- retry rate exists as a metric, but retry is not yet a first-class runtime behavior
- runs are durable, but multi-run continuation is not
- callers can cancel work, but cannot steer or queue follow-up instructions
- there is no checkpoint model for resume-after-failure or resume-after-interruption

## Design Goals

1. Preserve Forge as the outer runtime supervisor for Sophia.
2. Keep existing one-shot run semantics working for current clients.
3. Add long-running capabilities incrementally behind compatible APIs.
4. Make progress, retry, and resume behavior visible and auditable.
5. Keep backend-specific agent logic behind the backend adapter boundary.

## Non-Goals

1. Turn Forge into a terminal-first interactive coding agent.
2. Recreate Pi's full session UX, slash commands, or extension UI.
3. Require every backend to support interactive steering on day one.
4. Introduce distributed workers or multi-tenant auth in this phase.

## Summary

Add five capabilities in order:

1. streamed progress over SSE
2. scheduler-owned transient retry
3. durable `run_session` records above individual runs
4. queued control messages: `steer`, `follow_up`, `resume`
5. checkpoint artifacts plus compacted resume context

The key distinction is:

- `run`: one bounded execution attempt
- `run_session`: the durable envelope for a long-running task across multiple runs

Forge remains responsible for persistence, visibility, verification, and checkpointing. Backends remain responsible for doing the coding work.

## Proposed Architecture

### New Core Concepts

#### `run_session`

A durable record that groups one or more runs that belong to the same long-running task.

Responsibilities:

- own the user-facing task identity for long-running work
- accumulate attempts, checkpoints, and control messages
- provide a resume target after timeout, interruption, or operator steering
- expose a stable progress surface to clients

#### `control_message`

A durable instruction associated with a session or active run.

Initial message types:

- `steer`: adjust the current direction of work
- `follow_up`: queue additional work after current work completes
- `resume`: continue from the latest checkpoint or a chosen previous checkpoint

#### `checkpoint`

A Forge-owned persisted summary of resumable state.

Minimum checkpoint contents:

- source `run_id`
- source `session_id`
- compacted task/context summary
- changed file manifest at checkpoint time
- verification summary so far
- backend-facing resume prompt fragment
- artifact references needed to restore context

### State Model

The recommended lifecycle is:

1. client creates a session or submits a run without a session
2. Forge creates a session automatically for long-running mode or binds the run to an existing session
3. one or more runs execute inside the session
4. retry attempts stay within the session and are linked to a prior run
5. checkpoints are created after terminal runs and optionally after explicit milestones
6. control messages target the active session
7. session reaches terminal state when the client accepts completion or the runtime marks it failed/cancelled

## Protocol Changes

### `RunRequest`

Add optional fields:

```python
session_id: str | None = None
resume_from_run_id: str | None = None
resume_from_checkpoint_id: str | None = None
retry_policy: "RetryPolicy" = Field(default_factory=RetryPolicy)
long_running_mode: bool = False
```

Notes:

- `session_id` binds the run to a durable session.
- `resume_from_run_id` and `resume_from_checkpoint_id` make resume explicit and auditable.
- `long_running_mode` lets Forge apply richer progress/checkpoint behavior without changing existing callers.

### New `RetryPolicy`

```python
class RetryPolicy(BaseModel):
    mode: Literal["disabled", "transient_only"] = "disabled"
    max_attempts: int = 1
    initial_backoff_sec: float = 2.0
    max_backoff_sec: float = 30.0
```

Initial retry scope:

- backend launch failures classified as transient
- transport/provider timeouts
- provider overload or rate-limit failures surfaced by the backend

Do not retry:

- invalid output
- permission denied
- deterministic verification failures
- explicit user cancellation

### New `RunSession`

```python
class RunSession(BaseModel):
    session_id: str
    client_name: str
    task: str
    status: Literal[
        "active",
        "completed",
        "blocked",
        "failed",
        "cancelled",
    ]
    latest_run_id: str | None = None
    latest_checkpoint_id: str | None = None
    run_ids: tuple[str, ...] = ()
    created_at: str
    updated_at: str
    completed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### New `ControlMessage`

```python
class ControlMessage(BaseModel):
    control_id: str
    session_id: str
    run_id: str | None = None
    control_type: Literal["steer", "follow_up", "resume"]
    status: Literal["queued", "applied", "rejected", "cancelled"]
    message: str
    created_at: str
    applied_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### Event Model Additions

Extend `RunEventType` with:

- `run_progress`
- `run_heartbeat`
- `retry_scheduled`
- `retry_started`
- `retry_finished`
- `checkpoint_created`
- `control_message_queued`
- `control_message_applied`
- `control_message_rejected`
- `session_bound`
- `session_resumed`

Payload expectations:

- `run_progress`: coarse percent-like progress or milestone text, never fake precision
- `run_heartbeat`: timestamp plus backend-reported phase
- `retry_scheduled`: attempt number, reason, delay seconds
- `retry_started`: attempt number, prior run id
- `retry_finished`: terminal retry outcome
- `checkpoint_created`: checkpoint id, source run id
- `control_message_*`: control id, type, disposition reason

### Artifact Model Additions

Extend `ArtifactType` with:

- `checkpoint_summary`
- `checkpoint_context`
- `session_state`
- `progress_log`

Notes:

- `checkpoint_summary` is the compacted resume summary for the next run.
- `checkpoint_context` contains any structured resume payload needed by backends.
- `session_state` captures the current Forge-owned session envelope.
- `progress_log` stores streaming backend progress that is too large to fit comfortably in event payloads.

## API Changes

### Phase 1: Streaming on Existing Runs

Add:

- `GET /v1/runs/{run_id}/events/stream`

Behavior:

- Server-Sent Events stream.
- Starts with the current persisted event cursor.
- Emits new events as they are appended.
- Supports `after_sequence` query parameter for reconnect.

This should sit alongside the existing polling API rather than replacing it.

### Phase 2: Session APIs

Add:

- `POST /v1/sessions`
- `GET /v1/sessions/{session_id}`
- `GET /v1/sessions/{session_id}/runs`
- `GET /v1/sessions/{session_id}/checkpoints`

Recommended behavior:

- `POST /v1/sessions` creates a durable long-running task envelope without yet starting a run.
- clients may still create a run directly and let Forge auto-create a session when `long_running_mode=true`.

### Phase 3: Control APIs

Add:

- `POST /v1/sessions/{session_id}/control`
- `POST /v1/sessions/{session_id}/resume`

Initial semantics:

- `steer` and `follow_up` are always persisted immediately
- if the active backend can consume them mid-run, Forge applies them during the run
- otherwise Forge applies them at the next safe boundary, typically the next run in the session

### Compatibility

Keep the existing APIs unchanged:

- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/events`
- `GET /v1/runs/{run_id}/artifacts`
- `GET /v1/runs/{run_id}/verification`
- `POST /v1/runs/{run_id}/cancel`

Existing clients should continue to work without session awareness.

## Storage Changes

### New Tables

Add runtime-owned tables:

- `forge_run_sessions`
- `forge_run_session_runs`
- `forge_control_messages`
- `forge_checkpoints`

Suggested shapes:

#### `forge_run_sessions`

- `session_id`
- `client_name`
- `task`
- `status`
- `latest_run_id`
- `latest_checkpoint_id`
- `metadata_json`
- `created_at`
- `updated_at`
- `completed_at`

#### `forge_run_session_runs`

- `session_id`
- `run_id`
- `ordinal`
- `created_at`

#### `forge_control_messages`

- `control_id`
- `session_id`
- `run_id`
- `control_type`
- `status`
- `message`
- `metadata_json`
- `created_at`
- `applied_at`

#### `forge_checkpoints`

- `checkpoint_id`
- `session_id`
- `run_id`
- `summary_artifact_id`
- `context_artifact_id`
- `created_at`

### Existing Table Changes

Extend `forge_runs` metadata usage for:

- `session_id`
- `attempt`
- `retry_of_run_id`
- `resumed_from_checkpoint_id`

These fields already fit the current metrics pattern and should remain queryable.

## Scheduler Changes

### Phase 1: Progress Streaming

The scheduler should gain a small progress reporting surface.

Recommended internal interface:

```python
ProgressReporter = Callable[[str, dict[str, Any]], Awaitable[None]]
```

Backends may optionally emit:

- milestone text
- heartbeat
- retry classification hints

Forge remains the canonical emitter of persisted `RunEvent` records.

### Phase 2: Retry Loop

Refactor scheduler execution to wrap backend invocation in a bounded attempt loop:

1. prepare workspace and environment
2. run backend
3. classify failure
4. if retryable and attempts remain:
   - append `retry_scheduled`
   - sleep with backoff
   - append `retry_started`
   - create a new child run attempt in the same session
5. otherwise finalize normally

Important constraint:

- verification should run only on the terminal attempt that produced the finalized result

### Phase 3: Session Binding

Scheduler responsibilities expand to:

- create or bind sessions
- append `session_bound`
- update `latest_run_id`
- register checkpoints after terminal attempts
- enqueue queued control messages at the next safe execution boundary

### Phase 4: Resume Flow

Resume should work like this:

1. select the latest checkpoint unless a specific checkpoint is requested
2. synthesize a new `RunRequest` bound to the same `session_id`
3. inject checkpoint summary into the prompt package artifact
4. mark metadata with `resume_from_run_id` and `resume_from_checkpoint_id`
5. execute as a new run attempt

## Backend Interface Changes

The current backend contract can remain:

```python
async def run(request: RunRequest, *, env: Mapping[str, str] | None = None) -> RunResult
```

But add optional support for progress callbacks in the Forge executor layer:

```python
async def run(
    request: RunRequest,
    *,
    env: Mapping[str, str] | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> RunResult
```

Adoption model:

- Codex and Claude adapters may initially ignore `progress_reporter`
- newer backends can emit richer progress immediately
- scheduler still emits lifecycle events even when backends emit nothing extra

This keeps backend support incremental instead of blocking the whole plan on streaming-capable backends.

## Checkpoint Strategy

### Initial Checkpoint Policy

Create checkpoints:

- after every terminal run in a long-running session
- before every scheduler-owned retry
- before explicit `resume`

Checkpoint summary contents should include:

- original task
- current understanding of completed work
- changed files so far
- verification results so far
- unresolved blockers or follow-ups
- exact resume origin identifiers

### Compaction Policy

Do not attempt full conversational compaction at first.

Instead:

- compact Forge-owned artifacts into a backend-facing resume summary
- keep full artifacts on disk for auditability
- treat checkpoints as lossy operational summaries, not as the source of truth

This is the closest useful adaptation of Pi's compaction model without making Forge itself an agent session runtime.

## Client Changes

### `ForgeClient`

Recommended additions in `agents/sophia_prima/src/sophia/forge_client.py`:

- optional session creation/binding support
- SSE consumption path for active runs
- helper methods for `steer`, `follow_up`, and `resume`
- retry-aware polling fallback when SSE is unavailable

### Client Compatibility Strategy

Keep the current polling implementation as fallback.

Preferred order:

1. try SSE
2. fall back to polling `GET /v1/runs/{run_id}`
3. preserve inline mode as rollback for service outages

## Rollout Plan

### Phase A: Streamed Events

Deliverables:

- SSE endpoint
- event cursor/reconnect support
- richer progress event taxonomy

Exit criteria:

- clients can watch long runs without tight polling
- reconnect after disconnect resumes from last sequence

### Phase B: Runtime Retry

Deliverables:

- `RetryPolicy`
- transient failure classification
- bounded scheduler retry loop
- retry events and metrics

Exit criteria:

- transient backend/provider failures can recover automatically
- retry attempts are visible in events and metrics

### Phase C: Sessions

Deliverables:

- `RunSession` model
- session storage and APIs
- run-to-session linkage

Exit criteria:

- one long-running task can span multiple runs durably
- clients can inspect session state and run history

### Phase D: Control Messages

Deliverables:

- `ControlMessage` model
- `steer` and `follow_up` APIs
- safe-boundary control application

Exit criteria:

- clients can redirect long-running work without blind cancellation
- every control instruction is durably recorded

### Phase E: Checkpoints and Resume

Deliverables:

- checkpoint artifacts and storage
- resume API
- compacted resume summaries

Exit criteria:

- interrupted or timed-out work can resume from a checkpoint
- resumed runs are auditable and linked to their source checkpoints

## Testing Plan

Add tests for:

- SSE event ordering and reconnect from `after_sequence`
- retry classification and bounded backoff
- retry metrics and run linkage
- session creation and auto-binding from `long_running_mode`
- control message persistence and application ordering
- checkpoint artifact creation
- resume from latest and explicit checkpoint
- backward compatibility for existing run APIs

## Open Decisions

1. Whether SSE is sufficient initially or whether websocket support should be added at the same time.
2. Whether retries should create a new `run_id` per attempt or update one run record with attempt subrecords.
3. Whether control messages should be session-only or also target a specific active run.
4. How much backend progress detail should be persisted inline in events versus stored as artifacts.
5. Whether checkpoint creation should be mandatory for all long-running sessions or policy-driven.

## Recommendation

Implement in this order:

1. SSE plus richer event taxonomy
2. scheduler-owned retry
3. durable sessions
4. control messages
5. checkpoints and resume

This order gives immediate operational value, preserves backward compatibility, and improves long-running behavior without collapsing Forge into a second agent runtime.
