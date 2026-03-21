# Memory Architecture Upgrade Spec (Revised)

**Date:** 2026-03-21  
**Status:** Proposal  
**Supersedes:** `docs/memory_architecture_upgrade_spec.md`  
**Scope:** `agents/sophia_prima/src/sophia/memory/`, `agents/sophia_prima/src/sophia/history/`, `agents/sophia_prima/src/sophia/agent.py`, `agents/sophia_prima/src/sophia/skills/`

## Why This Revision Exists

The original proposal identified real gaps, but a few of its core assumptions were not accurate against the current codebase:

1. Memory is not re-queried on every inner-loop iteration today. It is built once per outer turn.
2. Freezing memory once per session would stale follow-up turns and degrade working-memory quality.
3. Memory/history/skill tools are not a natural fit for Pylon in their current form because they operate on agent-local state.
4. Replacing pre-activation skill injection with a `view_skill` tool would regress deterministic skill scoping.

This revised spec keeps the good parts of the plan while correcting those boundary mistakes.

## Current Architecture Summary

Sophia Prima currently has:

| Layer | Implementation | Storage |
|------|------|------|
| Procedural | `personality.md` + system prompt | Files |
| Lessons | Seed lessons + promoted directives | SQLite `memory_records` |
| Working | Recent messages from `ConversationContext` | In-memory |
| Episodic | One summary record per completed turn | SQLite `memory_records` |
| Semantic | Regex-extracted facts/preferences | SQLite `memory_records` |

Additional runtime behavior:

- Memory retrieval is hybrid-scored and built once per outer turn.
- Lossless history is persisted to `history_events` as an append-only log.
- Skills are matched before the model call and can scope allowed tools deterministically.
- Compaction is synchronous and heuristic.

## Design Goals

1. Stabilize prompt memory within a turn without staling future turns.
2. Put a hard ceiling on memory prompt footprint.
3. Add cross-session recall with a small, verifiable MVP.
4. Let the agent inspect and curate memory explicitly.
5. Improve compaction quality without adding turn latency.
6. Reduce skill-loading cost without breaking current activation behavior.

## Upgrade 1: Per-Turn Frozen Memory Snapshot

### Priority

Highest

### Problem

Memory is already built once per outer turn, not every inner-loop iteration. That means the current issue is narrower than originally stated:

- Intra-turn memory is already stable.
- Inter-turn memory is not explicitly controlled.
- A session-wide freeze would make follow-up turns stale because working memory depends on the latest `context.messages`.

### Revised Design

Freeze memory once per outer turn, not once per session.

The frozen unit should be a value object returned for that turn, not global mutable state on `MemoryManager`. This avoids cross-session contamination if multiple runs share one manager instance.

### Specification

Add a snapshot method that returns a prompt-ready frozen value for the current turn:

```python
@dataclass(frozen=True)
class FrozenMemorySnapshot:
    rendered_text: str
    created_at: datetime
    session_id: str
    query: str


class MemoryManager:
    def freeze_for_turn(
        self,
        *,
        session_id: str,
        query: str,
        messages: list[Message],
    ) -> FrozenMemorySnapshot:
        snapshot = self.recall(
            session_id=session_id,
            query=query,
            messages=messages,
        )
        text = snapshot.to_prompt_text(max_chars=self.config.max_snapshot_chars)
        return FrozenMemorySnapshot(
            rendered_text=text,
            created_at=utc_now(),
            session_id=session_id,
            query=query,
        )
```

In `SophiaAgent.run()`:

1. At the start of each outer turn, call `freeze_for_turn(...)`.
2. Store the returned `rendered_text` in a local `memory_context` variable.
3. Reuse that local value through the inner tool loop.
4. On the next outer turn, compute a new frozen snapshot from the updated conversation context.

### Notes

- `ingest_turn()` should continue to persist records after the final answer for the turn.
- Those writes should not affect the active turn's prompt because the turn already holds a frozen value.
- No `unfreeze()` API is required unless a future compression flow actually rewrites prompt context mid-turn.

### Files Changed

| File | Change |
|------|--------|
| `memory/manager.py` | Add `FrozenMemorySnapshot` support and `freeze_for_turn()` |
| `memory/types.py` | Optional home for `FrozenMemorySnapshot` |
| `agent.py` | Freeze memory once per outer turn and reuse local `memory_context` in the inner loop |

## Upgrade 2: Hard Snapshot Budget

### Priority

High

### Problem

Sophia limits item count and per-item length, but not total memory prompt size. The prompt can still expand unpredictably as lessons, episodic summaries, and semantic records accumulate.

### Revised Design

Enforce the budget on the actual rendered snapshot for the current turn. Do not try to infer next-turn limits from previous overshoot.

This should be exact, local, and deterministic.

### Specification

Add to `MemoryManagerConfig`:

```python
@dataclass(frozen=True)
class MemoryManagerConfig:
    ...
    max_snapshot_chars: int = 3000
```

Extend `MemorySnapshot.to_prompt_text()`:

```python
def to_prompt_text(self, max_chars: int | None = None) -> str:
    ...
```

If `max_chars` is set:

1. Render the full snapshot.
2. If the rendered text fits, return it unchanged.
3. Otherwise, remove content in this order until the rendered text fits:
   - semantic: lowest salience first
   - episodic: lowest salience first
   - working: oldest first
4. Never drop lessons automatically.
5. If lessons alone exceed the budget, keep lessons and truncate the final rendered text with an explicit suffix like `... [memory truncated]`.

### Rationale

This approach guarantees the current prompt fits. Retrieval-time heuristics do not.

### Files Changed

| File | Change |
|------|--------|
| `memory/manager.py` | Add `max_snapshot_chars` to config and pass it into rendering |
| `memory/types.py` | Add render-time budget enforcement |
| Tests | Add exact-fit and over-budget trimming cases |

## Upgrade 3: Cross-Session Search MVP

### Priority

Highest structural upgrade

### Problem

Lossless history exists, but it is only listable by session/run. There is no query path for recalling past sessions.

The original proposal indexed raw `payload_json`. That is too coarse for an MVP because:

- tool results can be very large
- JSON excerpts are noisy
- search quality will be dominated by irrelevant payload structure

### Revised Design

Index only extracted conversational text first:

- `TURN_INPUT.user_message`
- `TURN_OUTPUT.assistant_message`

Tool events remain in the history log, but they are out of scope for the first searchable layer.

### Specification

#### Phase 1: Searchable Text Column

Add nullable extracted text columns to `history_events`:

```sql
ALTER TABLE history_events ADD COLUMN search_text TEXT;
ALTER TABLE history_events ADD COLUMN display_text TEXT;
```

Rules:

- `TURN_INPUT`: `search_text = user_message`, `display_text = user_message`
- `TURN_OUTPUT`: `search_text = assistant_message`, `display_text = assistant_message`
- `TOOL_START` / `TOOL_END`: `search_text = NULL`, `display_text = NULL` for MVP

Backfill existing rows by parsing `payload_json`.

#### Phase 2: FTS5 Index

Create an FTS table over `search_text` only:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
    search_text,
    content='history_events',
    content_rowid='id'
);
```

Create triggers to keep the index in sync for rows where `search_text IS NOT NULL`.

#### Phase 3: Query API

Add to `SQLiteHistoryStore`:

```python
def search_sessions(
    self,
    *,
    query: str,
    exclude_session_ids: set[str] | None = None,
    max_sessions: int = 3,
    max_hits: int = 20,
    max_results_per_session: int = 5,
) -> list[SessionSearchResult]:
    ...
```

Behavior:

1. Query FTS for top matching rows.
2. Join back to `history_events`.
3. Group by `session_id`.
4. Exclude only the current `session_id` for MVP.
5. Return grouped text excerpts and date bounds.

#### Phase 4: Optional Summarization

Add a summarization wrapper on `LosslessHistoryManager`:

```python
async def search_sessions_summarized(
    self,
    *,
    query: str,
    exclude_session_ids: set[str] | None = None,
    max_sessions: int = 3,
    summarizer: Callable[[str, str], Awaitable[str]] | None = None,
) -> list[SessionRecap]:
    ...
```

If `summarizer` is absent, return raw grouped excerpts.

### Important Non-Goal

Do not promise session-lineage exclusion yet. The current system has `parent_run_id`, not `parent_session_id`. Excluding the current `session_id` is enough for phase 1.

### Files Changed

| File | Change |
|------|--------|
| `history/store.py` | Add extracted text columns, backfill migration, FTS5 setup, `search_sessions()` |
| `history/types.py` | Add `SessionSearchResult` and `SessionRecap` |
| `history/manager.py` | Add summarized wrapper |
| `agent.py` or local tool layer | Expose search as an agent-local tool |

## Upgrade 4: Agent-Local Memory Tools

### Priority

High

### Problem

Memory ingestion is passive. The agent cannot explicitly remember, forget, or inspect memory state.

The original proposal routed these through Pylon. That is the wrong boundary for now because memory state lives inside the agent process and its local store.

### Revised Design

Add an agent-local tool layer and register memory tools there.

The agent should merge:

- agent-local tools
- Pylon-backed service tools

into one tool list presented to the model.

### Tool Set

#### `remember`

```python
remember(
    content: str,
    level: str = "semantic",
    tags: list[str] | None = None,
) -> str
```

Writes a durable memory record after validation.

#### `forget`

```python
forget(
    substring: str,
    level: str | None = None,
) -> str
```

Deletes by substring match if the match set is unambiguous.

#### `list_memory`

```python
list_memory(
    level: str | None = None,
    limit: int = 10,
) -> str
```

Returns level, content, tags, and created time for inspection.

### Safety Validation

Create `memory/safety.py` to reject:

- role-hijack phrasing
- prompt-override phrasing
- obvious credential storage
- invisible Unicode
- oversized writes
- exact duplicates after normalization

### Store Support

Add to `MemoryStore`:

```python
def search_by_substring(
    self,
    *,
    substring: str,
    session_id: str | None = None,
    levels: set[MemoryLevel] | None = None,
) -> list[MemoryRecord]:
    ...
```

For `forget`, search across session-scoped records plus global records where relevant.

### Prompt Behavior

Writes from `remember` should not affect the current turn's prompt because the current turn uses a frozen snapshot. They naturally become visible on the next outer turn.

### Files Changed

| File | Change |
|------|--------|
| New: `memory/safety.py` | Validation helpers |
| `memory/store.py` | Add substring search |
| `agent.py` | Merge local tools with Pylon tools; execute local memory tools directly |
| New: local agent tool module | Define `remember`, `forget`, `list_memory` schemas and handlers |

## Upgrade 5: Model-Driven Compaction in Background

### Priority

Medium

### Problem

Current compaction is heuristic and synchronous. A better summary would help, but doing an LLM call inline at turn end would add user-visible latency.

### Revised Design

Keep the existing heuristic path as the synchronous default. Add an optional background compaction path that uses a cheap model and falls back safely.

### Specification

Add:

```python
async def compact_session_with_model(
    self,
    *,
    session_id: str,
    summarizer: Callable[[str], Awaitable[str]],
) -> bool:
    ...
```

Behavior:

1. Gather the same candidate batch used by current compaction.
2. Build a transcript from those episodic records.
3. Call the summarizer.
4. If it succeeds, write a semantic compaction record tagged `model_generated`.
5. If it fails, log and fall back to the existing heuristic summary.
6. Delete compacted episodic records only after a summary record is written successfully.

### Execution Model

Recommended options:

- background task after turn completion
- scheduled maintenance worker

Do not block the final answer on this summarizer call.

### Files Changed

| File | Change |
|------|--------|
| `memory/manager.py` | Add async model compaction path |
| `agent.py` or maintenance worker | Trigger background compaction |
| Tests | Verify fallback and deletion semantics |

## Upgrade 6: Skills Metadata-First Loading

### Priority

Low to medium

### Problem

Skill loading is already lazy at registry refresh time, but each discovered skill reads and stores the body immediately. Prompt injection also includes the full body for the matched skill.

The full replacement proposed in the original spec would break deterministic pre-activation and tool scoping.

### Revised Design

Preserve the current contract:

- skill match happens before model call
- matched skill can still scope tools deterministically
- the system prompt still receives matched-skill instructions

Only change how the registry stores skill data:

- load frontmatter for all skills during refresh
- load body on demand only for the matched skill

### Specification

Add metadata-only loading:

```python
load_skill(path, max_body_chars=..., metadata_only=True)
```

Extend `SkillRegistry`:

```python
def get_skill_body(self, name: str) -> str: ...
```

At match time:

1. Find the best skill from metadata.
2. Load its body on demand.
3. Preserve existing prompt injection and tool allowlist logic.

### Optional Later Extension

A `view_skill` tool can be added later, but it is not required for the first optimization pass.

### Files Changed

| File | Change |
|------|--------|
| `skills/loader.py` | Add metadata-only parsing mode |
| `skills/registry.py` | Cache metadata, load body on demand |
| `agent.py` | Continue injecting matched skill body, but only after on-demand load |
| Tests | Preserve current skill activation and tool scoping behavior |

## Revised Implementation Sequence

### Phase 1: Defensive Prompt Control

1. Per-turn frozen memory snapshot
2. Hard snapshot budget

### Phase 2: Cross-Session Recall MVP

1. Extracted searchable text in history rows
2. FTS5 index
3. Grouped session search
4. Optional summarization wrapper

### Phase 3: Agent Memory Curation

1. Agent-local tool registry
2. `remember`
3. `forget`
4. `list_memory`
5. Safety validation

### Phase 4: Quality Improvements

1. Background model compaction
2. Skills metadata-first loading

## Testing Strategy

Each phase should ship with focused tests:

- Unit tests for `freeze_for_turn()` and budget trimming.
- Integration test proving `ingest_turn()` does not mutate the current turn's frozen memory.
- Migration test for history search backfill on an existing `history_events` DB.
- Query tests for session grouping and current-session exclusion.
- Tool tests for `remember`, `forget`, and `list_memory`, including safety rejections.
- Regression tests preserving current skill activation and tool allowlist behavior.
- Compaction tests covering summarizer success, failure fallback, and deletion ordering.

## What We Are Explicitly Not Doing

| Idea | Decision | Reason |
|------|----------|--------|
| Session-wide memory freeze | Reject | Follow-up turns would use stale working memory and stale query context. |
| Pylon-hosted memory/history tools | Reject for now | These tools operate on agent-local state, not backend services. |
| Search over raw tool-result JSON first | Reject for MVP | Too noisy, too large, and hard to summarize cleanly. |
| Replace skill activation with `view_skill` only | Reject | Would break deterministic pre-call tool scoping. |
| Inline LLM compaction on turn end | Reject | Adds avoidable latency to the user-facing path. |

## Recommendation

The best near-term path is:

1. Stabilize and budget prompt memory per turn.
2. Add a narrow but reliable cross-session recall path.
3. Add agent-local memory curation tools.
4. Improve compaction and skill loading only after those foundations are in place.

That sequence fixes the highest-value architectural gaps without breaking the current agent/tool contract.
