# Memory Architecture Upgrade Spec

**Date:** 2026-03-21
**Status:** Proposal
**Scope:** `agents/sophia_prima/src/sophia/memory/`, `agents/sophia_prima/src/sophia/history/`, `agents/sophia_prima/src/sophia/agent.py`

## Background

Sophia Prima's memory system implements a 5-level taxonomy (Procedural, Lessons, Working, Episodic, Semantic) with SQLite persistence, hybrid retrieval scoring, and heuristic compaction. This is a solid foundation, but a comparative analysis of the Hermes Agent architecture (NousResearch/hermes-agent) reveals several structural gaps that limit Sophia's continuity, prompt efficiency, and memory quality.

This document specifies six upgrades, ordered by priority, that adopt the highest-value Hermes patterns while preserving Sophia's existing strengths (richer taxonomy, pluggable embeddings, salience-weighted retrieval).

## Current Architecture Summary

### What Sophia Has

| Layer | Implementation | Storage |
|-------|---------------|---------|
| Procedural | `personality.md` + system prompt | Files (static) |
| Lessons | `LESSONS.md` seeds + auto-promoted from corrections | SQLite `memory_records` |
| Working | Last N messages from `ConversationContext` | In-memory |
| Episodic | Turn summaries written after each turn | SQLite `memory_records` |
| Semantic | Regex-extracted facts (name, role, preferences) | SQLite `memory_records` |

- **Retrieval:** Hybrid scoring (lexical overlap + sparse semantic vectors + salience + recency decay), run fresh every turn.
- **History:** `LosslessHistoryManager` stores raw turn/tool events in a separate SQLite DB (`history_events`). Append-only audit log with no query surface.
- **Skills:** `SkillRegistry` discovers SKILL.md files, matches by keyword overlap, injects full body into system prompt.
- **Compaction:** Heuristic text truncation of oldest episodic records into a bullet-list summary.

### Key Gaps

1. **No prompt stability** — Memory is re-queried and re-injected every inner-loop iteration, defeating provider-side prefix caching.
2. **No cross-session recall** — History DB has full fidelity but no search interface. Memory is scoped per `session_id`.
3. **No agent-callable memory tools** — Ingestion is passive (regex only). The agent cannot explicitly remember or forget.
4. **Heuristic compaction** — Summaries are text-truncated, not model-generated. Loses implicit decisions and nuance.
5. **No aggregate memory budget** — Per-record truncation and k-limits exist, but no cap on total prompt footprint from memory.
6. **Eager skill loading** — Full skill body injected on match; no progressive disclosure pattern.

---

## Upgrade 1: Frozen Memory Snapshot

### Priority: Highest
### Effort: Low
### Dependencies: None

### Problem

`agent.py:1655-1659` calls `self.memory.recall_for_prompt()` on every inner-loop iteration. This produces a different `memory_context` string each turn (different recency scores, different working memory window), which mutates the system prompt and prevents Anthropic prefix caching.

Additionally, memory ingested mid-session (from turn N's `ingest_turn()`) can contaminate retrieval for turn N+1, creating a feedback loop where the model responds to its own summarized outputs.

### Design

Capture a frozen memory snapshot once per session. Mid-session writes persist to the store but do not affect the prompt until a deliberate re-freeze event (compression, session restart).

### Specification

#### New methods on `MemoryManager`

```python
class MemoryManager:
    def __init__(self, ...):
        ...
        self._frozen_text: str | None = None
        self._frozen_at: datetime | None = None

    def freeze(
        self,
        *,
        session_id: str,
        query: str,
        messages: list[Message],
    ) -> str:
        """Capture and freeze a memory snapshot. Returns the prompt text."""
        self._frozen_text = self.recall_for_prompt(
            session_id=session_id,
            query=query,
            messages=messages,
        )
        self._frozen_at = utc_now()
        return self._frozen_text

    def get_frozen(self) -> str:
        """Return the frozen snapshot, or empty string if not yet frozen."""
        return self._frozen_text or ""

    def is_frozen(self) -> bool:
        return self._frozen_text is not None

    def unfreeze(self) -> None:
        """Clear the frozen snapshot (triggers re-freeze on next access)."""
        self._frozen_text = None
        self._frozen_at = None
```

#### Changes to `SophiaAgent._run_conversation()`

```python
# At the start of run(), before the outer turn loop:
memory_context = self.memory.freeze(
    session_id=context.session_id,
    query=active_user_message,
    messages=context.messages,
)

# In the inner loop (replacing lines 1655-1659):
memory_context = self.memory.get_frozen()
```

#### Re-freeze triggers

- After `compact_session()` completes.
- After any future compression/context-window collapse.
- NOT after `ingest_turn()` — mid-session writes are deferred to next freeze.

### Files Changed

| File | Change |
|------|--------|
| `memory/manager.py` | Add `freeze()`, `get_frozen()`, `is_frozen()`, `unfreeze()` |
| `agent.py:1655-1659` | Replace live `recall_for_prompt()` with `get_frozen()` |
| `agent.py` (outer loop start) | Add `freeze()` call before first turn |
| `agent.py` (post-compaction) | Add `unfreeze()` + re-`freeze()` after compaction |

---

## Upgrade 2: Memory Budget Cap

### Priority: High
### Effort: Low
### Dependencies: None (pairs naturally with Upgrade 1)

### Problem

Sophia has `max_item_chars=240` per record and configurable `k` per level, but no aggregate ceiling on total memory prompt footprint. As the store grows, the combined snapshot can expand unpredictably, consuming context window and increasing cost.

### Design

Add a hard character budget to `MemoryManagerConfig`. When the rendered snapshot exceeds the budget, trim from the lowest-salience records first, preserving lessons (highest priority) and working memory (most recent context).

### Specification

#### New config field

```python
@dataclass(frozen=True)
class MemoryManagerConfig:
    ...
    max_snapshot_chars: int = 3000  # ~750 tokens
```

#### Budget enforcement in `MemorySnapshot.to_prompt_text()`

Add a `to_prompt_text(max_chars: int | None = None)` parameter. When set:

1. Render full text as today.
2. If `len(text) <= max_chars`, return as-is.
3. Otherwise, drop records in priority order: semantic (lowest salience first) → episodic (lowest salience first) → working (oldest first). Never drop lessons.
4. Re-render after each drop until under budget.

#### Alternative: enforce in `recall()`

Instead of trimming rendered text, enforce the budget at retrieval time by reducing `k` values dynamically. This is cleaner because it avoids partial rendering, but less precise about character cost.

**Recommended approach:** Enforce in `recall()` — reduce `semantic_recall_k` and `episodic_recall_k` dynamically if the rendered snapshot from the previous freeze exceeded budget. Store the overshoot as state and adjust on next freeze.

### Files Changed

| File | Change |
|------|--------|
| `memory/types.py` | Add `max_chars` parameter to `to_prompt_text()` |
| `memory/manager.py` | Add `max_snapshot_chars` to config, enforce in `freeze()` |

---

## Upgrade 3: Cross-Session Search

### Priority: Highest (structural)
### Effort: Medium
### Dependencies: FTS5 migration on `history_events` table

### Problem

`LosslessHistoryManager` stores full-fidelity turn/tool history in SQLite (`history_events` table), but this is an append-only audit log with no query interface. The agent has no way to recall past sessions. Memory is scoped to `session_id` — there is no cross-session path.

Hermes solves this with FTS5 full-text search over all messages, session grouping, parent-chain resolution, and cheap-model summarization of matching sessions.

### Design

Add FTS5 indexing to the existing `history_events` table. Expose a `search_sessions()` method that returns summarized recaps of matching past sessions. Register as a Pylon tool so the agent can invoke it.

### Specification

#### Phase 1: FTS5 Migration

Add to `SQLiteHistoryStore._ensure_schema()`:

```sql
-- FTS5 virtual table over history event payloads
CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
    search_text,
    content=history_events,
    content_rowid=id
);

-- Sync triggers
CREATE TRIGGER IF NOT EXISTS history_fts_insert AFTER INSERT ON history_events BEGIN
    INSERT INTO history_fts(rowid, search_text)
    VALUES (new.id, new.payload_json);
END;

CREATE TRIGGER IF NOT EXISTS history_fts_delete AFTER DELETE ON history_events BEGIN
    INSERT INTO history_fts(history_fts, rowid, search_text)
    VALUES ('delete', old.id, old.payload_json);
END;
```

Note: `payload_json` contains the raw user/assistant messages as JSON. FTS5 will match against the full JSON text, which works well enough since the message content dominates. A refinement would extract just the text fields, but this is a clean first pass.

#### Phase 2: Search Method

Add to `SQLiteHistoryStore`:

```python
def search_sessions(
    self,
    *,
    query: str,
    exclude_session_ids: set[str] | None = None,
    max_sessions: int = 3,
    max_results_per_session: int = 5,
    max_excerpt_chars: int = 2000,
) -> list[SessionSearchResult]:
    """Search past sessions via FTS5, return grouped excerpts."""
```

Flow:
1. FTS5 query: `SELECT rowid, rank FROM history_fts WHERE search_text MATCH ? ORDER BY rank LIMIT 50`
2. Join back to `history_events` to get `session_id`, `created_at`, `payload_json`.
3. Group by `session_id`, excluding `exclude_session_ids`.
4. For each of the top `max_sessions`, collect the top-ranked event payloads.
5. Truncate around match regions to `max_excerpt_chars` per session.
6. Return `SessionSearchResult(session_id, created_at_range, excerpts)`.

#### Phase 3: Summarization Layer

Add to `LosslessHistoryManager`:

```python
async def search_sessions_summarized(
    self,
    *,
    query: str,
    exclude_session_ids: set[str] | None = None,
    max_sessions: int = 3,
    summarizer: Callable[[str, str], Awaitable[str]] | None = None,
) -> list[SessionRecap]:
    """Search + summarize matching past sessions."""
```

The `summarizer` callable takes `(query, transcript_excerpt)` and returns a focused summary. The caller (agent or Pylon tool) provides this — typically a cheap model call (Groq Llama, Gemini Flash).

If `summarizer` is None, return raw excerpts (useful for testing, low-cost fallback).

#### Phase 4: Pylon Tool

Register `session_recall` as a Pylon tool:

```python
@tool(
    name="session_recall",
    description="Search past conversation sessions for relevant context. "
                "Use when the user references prior discussions or you need "
                "historical context not in current memory.",
)
async def session_recall(query: str, max_sessions: int = 3) -> str:
    ...
```

The tool should automatically exclude the current session's lineage (current `session_id` + parent chain).

#### New Types

```python
@dataclass(frozen=True)
class SessionSearchResult:
    session_id: str
    earliest: datetime
    latest: datetime
    excerpts: list[str]  # truncated event payloads
    match_count: int

@dataclass(frozen=True)
class SessionRecap:
    session_id: str
    earliest: datetime
    latest: datetime
    summary: str  # model-generated or raw excerpt
    match_count: int
```

### Files Changed

| File | Change |
|------|--------|
| `history/store.py` | FTS5 migration, `search_sessions()` method |
| `history/types.py` | `SessionSearchResult`, `SessionRecap` types |
| `history/manager.py` | `search_sessions_summarized()` passthrough |
| New: Pylon tool | `session_recall` tool registration |
| `agent.py` | Wire tool into available tools, pass current session exclusion |

### Migration Note

Existing `history_events` tables won't have FTS5 or triggers. The migration should:
1. Create the FTS5 table and triggers if they don't exist.
2. Backfill the FTS5 index from existing rows: `INSERT INTO history_fts(rowid, search_text) SELECT id, payload_json FROM history_events`.

This is safe to run on an existing DB — FTS5 creation is idempotent with `IF NOT EXISTS`, and the backfill INSERT is additive.

---

## Upgrade 4: Agent-Callable Memory Tools

### Priority: High
### Effort: Low
### Dependencies: Upgrade 1 (frozen snapshot ensures writes don't mutate prompt mid-session)

### Problem

Sophia's memory ingestion is entirely passive — regex patterns in `_extract_semantic_facts()` run on user text after each turn. The agent cannot explicitly remember a fact, forget an outdated one, or inspect its own memory state. This is listed as a planned extension in MEMORY_MODEL.md line 109.

### Design

Three Pylon tools: `remember`, `forget`, `list_memory`. Writes go to the SQLite store immediately but do not affect the frozen prompt snapshot (they appear in the next session's freeze).

### Specification

#### `remember` Tool

```python
@tool(
    name="remember",
    description="Save a durable fact, preference, or lesson to memory. "
                "Saved memories persist across sessions but take effect "
                "in the next session's memory snapshot.",
)
def remember(
    content: str,
    level: str = "semantic",  # "semantic" | "lessons"
    tags: list[str] | None = None,
) -> str:
    ...
```

Validation before write:
- Reject content matching injection patterns (role hijack, system prompt override).
- Reject content containing credential patterns (`API_KEY`, `SECRET`, `PASSWORD` followed by `=` or `:`).
- Reject content with invisible Unicode (U+200B, U+200C, U+200D, U+FEFF).
- Reject exact duplicates (normalize whitespace, compare against existing records in target level).
- Enforce per-write size limit (e.g., 500 chars).

Returns confirmation with record count and total memory usage.

#### `forget` Tool

```python
@tool(
    name="forget",
    description="Remove a memory record by matching a unique substring. "
                "Takes effect in the next session's memory snapshot.",
)
def forget(
    substring: str,
    level: str | None = None,  # if None, search all levels
) -> str:
    ...
```

Flow:
1. Search all records (or records at the given level) for those containing `substring` (case-insensitive).
2. If exactly one match (or all matches have identical content): delete and confirm.
3. If multiple distinct matches: return the matches and ask the user to be more specific.
4. If no matches: return "no matching memory found."

Requires new method on `MemoryStore`:
```python
def search_by_substring(
    self,
    *,
    substring: str,
    session_id: str | None = None,
    levels: set[MemoryLevel] | None = None,
) -> list[MemoryRecord]:
```

#### `list_memory` Tool

```python
@tool(
    name="list_memory",
    description="List current memory records, optionally filtered by level.",
)
def list_memory(
    level: str | None = None,
    limit: int = 10,
) -> str:
    ...
```

Returns a formatted list of records with content, level, tags, and created_at. Useful for the agent to audit its own state before deciding what to remember or forget.

#### Security Module

Create `memory/safety.py`:

```python
INJECTION_PATTERNS = [
    r"(?i)\b(system|assistant|user)\s*:",  # role hijack
    r"(?i)ignore\s+(previous|above|all)\s+instructions",
    r"(?i)you\s+are\s+now\b",
    r"(?i)new\s+instructions?\s*:",
]

EXFILTRATION_PATTERNS = [
    r"(?i)(curl|wget|fetch)\s+.*\$",
    r"(?i)cat\s+.*\.(env|key|pem|secret)",
    r"(?i)(API_KEY|SECRET|PASSWORD|TOKEN)\s*[=:]",
]

INVISIBLE_UNICODE = {'\u200b', '\u200c', '\u200d', '\ufeff', '\u2060'}

def validate_memory_content(content: str) -> str | None:
    """Return error message if content is unsafe, else None."""
    ...
```

### Files Changed

| File | Change |
|------|--------|
| New: `memory/safety.py` | Injection/exfiltration/unicode validation |
| `memory/store.py` | Add `search_by_substring()` to both store implementations |
| New: Pylon tools | `remember`, `forget`, `list_memory` tool registrations |
| `agent.py` | Register memory tools in available tool set |

---

## Upgrade 5: LLM-Driven Compaction

### Priority: Medium
### Effort: Medium
### Dependencies: Access to a cheap/fast model for summarization

### Problem

`compact_session()` in `manager.py:193-226` builds summaries by truncating episodic record content into a bullet list (`_build_compaction_summary`). This is fast and deterministic but loses implicit decisions, nuance, and cross-turn patterns that a model would preserve.

### Design

Replace the heuristic summary with a cheap-model call that extracts durable facts from a batch of episodic records before they're deleted.

### Specification

#### New compaction flow

```python
async def compact_session_with_model(
    self,
    *,
    session_id: str,
    summarizer: Callable[[str], Awaitable[str]],
) -> None:
    """Compact using an LLM for higher-quality summaries."""
    # Same threshold logic as compact_session()
    ...
    # Build transcript from batch
    transcript = "\n".join(
        f"- {rec.content}" for rec in compact_batch
    )
    # LLM summarization
    summary = await summarizer(transcript)
    # Write semantic record
    self.store.add(MemoryRecord(
        level=MemoryLevel.SEMANTIC,
        session_id=session_id,
        content=summary,
        tags={"compaction", "episodic_summary", "model_generated"},
        salience=self._average_salience(compact_batch),
        metadata={
            "source": "compaction_llm",
            "compacted_ids": [rec.id for rec in compact_batch],
            "model": "cheap",  # caller fills in actual model name
        },
    ))
    self.store.delete_ids([rec.id for rec in compact_batch])
```

#### Summarization prompt

```
You are summarizing a batch of conversation turn records for long-term memory.

Extract and preserve:
- User preferences and corrections
- Decisions made and their rationale
- Recurring patterns or themes
- Project constraints discovered
- Facts about the user's identity, role, or goals

Do NOT preserve:
- Task-specific intermediate steps
- Tool call details (keep conclusions, not process)
- Conversational filler or greetings

Return a concise summary (200-400 words) structured as a list of durable facts.

Turn records:
{transcript}
```

#### Fallback

If the summarizer call fails (timeout, API error), fall back to the existing heuristic `_build_compaction_summary()`. Log the failure for monitoring.

#### Caller provides the summarizer

The `SophiaAgent` constructs the summarizer callable using a cheap model provider (Groq Llama, OpenAI gpt-4.1-nano, etc.). This keeps the memory module provider-agnostic.

### Files Changed

| File | Change |
|------|--------|
| `memory/manager.py` | Add `compact_session_with_model()`, keep `compact_session()` as fallback |
| `agent.py` | Wire cheap-model summarizer into compaction path |

---

## Upgrade 6: Skills Progressive Disclosure

### Priority: Low (grows with skill count)
### Effort: Medium
### Dependencies: Pylon tool

### Problem

When a skill matches, `_build_system_prompt()` (agent.py:498-522) injects the full SKILL.md body into `dynamic_context["Active skill"]`. As the skill library grows, this eager injection consumes prompt budget. Additionally, all SKILL.md files are loaded into memory at `refresh()` time regardless of whether they'll be used.

### Design

Inject a compact skills index (name + description) into the system prompt. Add a `view_skill` Pylon tool for on-demand full-body loading. The agent sees what's available cheaply and pulls detail when needed.

### Specification

#### Skills index injection

Add to `_build_system_prompt()`:

```python
if self.skills.enabled:
    skills_list = self.skills.list_skills()
    if skills_list:
        index_lines = [f"- **{s.name}**: {s.description}" for s in skills_list]
        dynamic_context["Available skills"] = (
            "Use the view_skill tool to load full instructions.\n"
            + "\n".join(index_lines)
        )
```

Remove the current full-body injection in the `active_skill` block (lines 498-522). Instead, skill activation happens when the agent calls `view_skill` and receives the instructions.

#### `view_skill` Pylon tool

```python
@tool(
    name="view_skill",
    description="Load the full instructions for a named skill.",
)
def view_skill(name: str) -> str:
    ...
```

Returns the full SKILL.md body for the named skill, or an error if not found.

#### Lazy body loading in `SkillRegistry`

Change `load_skill()` to support a `metadata_only=True` mode that parses frontmatter but skips reading the full body. The body is loaded on demand when `view_skill` is called.

### Files Changed

| File | Change |
|------|--------|
| `skills/loader.py` | Add `metadata_only` parameter to `load_skill()` |
| `skills/registry.py` | Lazy body loading, add `get_skill_body(name)` |
| New: Pylon tool | `view_skill` tool registration |
| `agent.py:498-522` | Replace full-body injection with compact index |

---

## Implementation Sequence

```
Phase 1 (defensive, no new features):
  ├── Upgrade 1: Frozen memory snapshot
  └── Upgrade 2: Memory budget cap

Phase 2 (cross-session continuity):
  └── Upgrade 3: Cross-session search
      ├── 3a: FTS5 migration + search_sessions()
      ├── 3b: Summarization layer
      └── 3c: Pylon tool registration

Phase 3 (agent memory curation):
  └── Upgrade 4: Agent-callable memory tools
      ├── 4a: Safety validation module
      ├── 4b: remember / forget / list_memory tools
      └── 4c: search_by_substring() on store

Phase 4 (quality improvements):
  ├── Upgrade 5: LLM-driven compaction
  └── Upgrade 6: Skills progressive disclosure
```

Phases 1 and 2 are independent and can be parallelized. Phase 3 depends on Phase 1 (frozen snapshot must be in place so memory writes don't mutate the prompt mid-session). Phase 4 items are independent of each other.

## Testing Strategy

Each upgrade should include:

- **Unit tests** for new methods (freeze/unfreeze, search_by_substring, FTS5 queries, safety validation).
- **Integration test** verifying that mid-session `ingest_turn()` does NOT change `get_frozen()` output.
- **Integration test** verifying FTS5 backfill on existing DB migration.
- **Regression tests** on existing `test_memory_manager.py` and `test_memory_store.py` to confirm no behavioral change in recall/compaction for the non-frozen path.

## What We're NOT Adopting from Hermes

| Hermes Feature | Decision | Reason |
|----------------|----------|--------|
| Plain-text `§`-delimited files | Skip | Sophia's SQLite store is strictly better for query, compaction, and embedding indexing. |
| Character-limit-based memory (vs token) | Partial | We adopt the budget cap concept but keep it as a config knob rather than a hard file format constraint. |
| Honcho user modeling layer | Skip for now | Sophia's semantic memory level already captures user preferences and identity. Cross-session search (Upgrade 3) covers the continuity gap. Honcho-style modeling is a future consideration if multi-user support is needed. |
| Frozen snapshot = file on disk | Skip | Sophia's freeze is in-memory per session. We don't need file-based persistence because the SQLite store already persists the underlying records. |
| Compression-triggered session splitting | Skip for now | Hermes creates child sessions with `parent_session_id` linkage for compression continuity. Sophia's session model doesn't currently support this. Consider if/when a context-window compression feature is added. |
