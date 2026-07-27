# Sophia Memory Model (v1)

## Goal

Define an explicit multi-level memory framework for `sophia_prima` with clear
purposes and time horizons, inspired by recent multi-memory agent patterns.

## Memory Levels

| Level | Purpose | Typical Timeframe | Current Status |
|------|---------|-------------------|----------------|
| Procedural | Persona, behavior constraints, tool policy | Weeks to months | Implemented via `personality.md` + system prompt |
| Working | Recent turn context and local interaction state | Seconds to hours | Implemented via `ConversationContext` + context transforms |
| Episodic | Compressed turn summaries (what user asked, what happened) | Days to weeks | Implemented in `MemoryManager.ingest_turn()` |
| Semantic | Durable user/project facts and preferences | Weeks to months | Implemented with heuristic fact extraction in `MemoryManager` |

## Runtime Flow

1. Before each outer turn, the agent builds a memory snapshot:
   - Working memory from recent user/assistant lines.
   - Episodic recalls from session-scoped turn summaries.
   - Semantic recalls from extracted stable facts/preferences.
2. Snapshot is injected into dynamic system prompt context as `Memory context`.
3. After final assistant response for the turn:
   - One episodic memory record is written.
   - Semantic facts are extracted from user text and written.

## Design Notes

- Memory is scoped per session (`session_id`) for now.
- Retrieval uses lexical overlap + salience + recency decay.
- Prompt text includes guardrails:
  - Use memory conservatively.
  - Prefer current explicit user input when memory conflicts.

## Persistence + Compaction (Implemented)

- `SQLiteMemoryStore` persists records to `memory_records` in a local SQLite DB.
- Backend selection is configurable:
  - `memory_store_backend=sqlite|memory`
  - `memory_store_path=...` (used for SQLite)
- Compaction is configurable and enabled by default:
  - `memory_compaction_enabled=true`
  - `memory_compaction_every_n_turns=10`
  - `memory_compaction_max_episodic_per_session=120`
  - `memory_compaction_batch_size=40`
- Compaction behavior:
  - When episodic count exceeds threshold, oldest episodic records are merged into one
    semantic summary record tagged with `compaction` and `episodic_summary`.
  - Compacted episodic records are deleted.

## Retrieval (Hybrid)

- Memory retrieval uses a hybrid score:
  - lexical overlap (token intersection)
  - semantic similarity (hashed sparse semantic vectors + synonym normalization)
  - salience, recency decay, and session bonus
- Controls:
  - `memory_semantic_search_enabled`
  - `memory_lexical_weight`
  - `memory_semantic_weight`

## Async Embedding Index (Implemented)

- New records can be marked `pending` for embedding indexing.
- `sophia-memory-index` processes pending records in batches and writes vectors to
  `memory_embeddings` in SQLite.
- Agent-time retrieval uses indexed vectors when present, with fallback to local
  semantic scoring when needed.
- Embedding provider is pluggable:
  - `memory_embedding_provider=hash` (default local)
  - `memory_embedding_provider=openai` (external embeddings)
- Cron-style usage example:
  - `*/5 * * * * cd /path/to/agents/sophia_prima && PYTHONPATH=src sophia-memory-index`

## Logging and Metrics

- Indexer logs start/batch/end records with:
  - processed, ready, failed
  - batches
  - backlog before/after
- Configure via `memory_log_level` (`DEBUG|INFO|WARNING|ERROR`).

## External Provider Resilience

- OpenAI embedding provider supports retry/backoff for transient failures:
  - HTTP: `429`, `500`, `502`, `503`, `504`
  - network errors (`URLError`)
- Backoff controls:
  - `memory_embedding_retry_max_attempts`
  - `memory_embedding_retry_base_ms`
  - `memory_embedding_retry_max_ms`
  - `memory_embedding_retry_jitter`

## Current Limitations

- Semantic extraction is rule-based; no model-based consolidation yet.
- Compaction summaries are heuristic and text-truncated (not LLM-generated).
- OpenAI provider uses direct HTTP calls and currently has no retry/backoff policy.
- No contradiction resolution policy across semantic records yet.

## Next Extensions

1. Add model-based consolidation from episodic -> semantic (reflection pass).
2. Add memory quality controls:
   - dedupe by semantic similarity
   - contradiction handling
   - confidence decay over time
3. Add explicit memory tools (`remember`, `forget`, `list_memory`) for user control.
4. Add external embedding providers (OpenAI/local model server) for stronger retrieval quality.
