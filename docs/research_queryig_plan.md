## Merged Proposal

Goal: fast, low-token querying over rich research JSON with hybrid search, metadata filters, and minimal ops, tuned for thematic/jargon-heavy queries.

Core architecture:
- Source of truth: existing JSON (themes, trade ideas, metadata, summaries, full text).
- Storage: PostgreSQL + pgvector (single system).
- Indexes:
  - GIN on themes/trade_ideas/metadata JSONB for filtering.
  - tsvector for lexical search + jargon lexicon boosting.
  - pgvector embeddings on text chunks for semantic search.
- Optional "summary index" for discovery:
  - One-row-per-paper: title + 1-line summary + themes + key trade idea.
  - Used only for browsing; fetch full chunks on demand.

Query flow (token-minimizing):
1) Parse intent + filters (dates, themes, sources, asset class, jargon).
2) Route to lexical, vector, or hybrid (heuristics with jargon boost).
3) Apply metadata filters first to shrink candidate set (date, source, asset class).
4) Retrieve top-N chunks; optionally rerank top-K.
5) Assemble context with strict token cap; include lightweight citations for debugging.

Embedding & chunking:
- Embed summaries + full text chunks (500-800 tokens); embed trade ideas only if needed.
- Skip embedding fields already captured by metadata filters when not needed.

Caching:
- Paper/theme/trade-idea summary cache (precompute).
- Query-level cache with TTL; invalidate on new rows (append-only).

Ingestion pipeline (daily):
1) Find new/updated rows.
2) Upsert metadata fields; update summary index row.
3) Chunk text; generate embeddings in batches; upsert vectors.
4) Rebuild tsvector fields and metadata indexes.
5) Invalidate caches touched by new content.

Implementation phases:
1) Postgres schema + GIN/tsvector; basic metadata filtering.
2) Embedding pipeline + pgvector; vector search.
3) Hybrid retrieval + routing heuristics (jargon-aware).
4) Cache + context assembly + optional reranker; optimize for 2-5s latency.

Trade-offs:
- Postgres-only keeps ops simple but may need Elastic later for complex lexical needs.
- Summary index speeds browsing but adds a small extra artifact to maintain.
- Reranking improves precision but adds compute; keep optional.

## Context Snapshot (Use Cases + Implications)

- Primary query types: thematic, specified-source, and generalized queries; no ticker lookups.
- Filters: frequent date ranges; regular source/asset class filters; author filters not needed.
- Retrieval focus: full-text context over trade ideas; multi-hop synthesis across papers.
- Language: jargon-sensitive lexical matching required; semantic search must not drop domain terms.
- Ops/latency: append-only ingest enables simple invalidation; end-state 2-5s latency target.
- Traceability: lightweight citations for debugging only.

## Annotated Phase Plan

Phase 1: Database Schema + Metadata Filtering (12 tasks)
- Focus: PostgreSQL setup with pgvector, new models, GIN indexes
- Key tasks:
  - Add pgvector extension (Supabase project setting + migration)
  - Create ResearchPaper, ResearchChunk, SummaryIndex, SummaryCache, QueryCache models in scrivener/src/db/models.py
  - Add Alembic/DDL migrations for new tables and indexes
  - GIN indexes on themes/trade_ideas JSONB; B-tree on date/source/asset_class
  - Add tsvector column + GIN index (set up now, used in Phase 3)
  - Research JSON ingestion fetcher (extends existing scrivener/fetchers/base.py pattern)
  - Append-only ingestion: new rows only detection + idempotent upserts
  - Backfill job for existing corpus (one-time)
  - Basic Pylon tools: filter_by_theme, filter_by_source, filter_by_date_range, filter_by_asset_class

Phase 2: Embedding Pipeline + Vector Search (8 tasks)
- Focus: Semantic search infrastructure
- Key tasks:
  - Add embedding SDK dependency (OpenAI/Anthropic)
  - Central config for embedding model/version + chunk size + tokenizer
  - Chunking utility (500-800 tokens)
  - Batch embedding generation for summaries + full text
  - HNSW/IVFFlat vector index on embeddings (confirm support in Supabase)
  - Daily scheduled job for incremental embedding (APScheduler)
  - Retry/backoff + rate-limit guardrails
  - semantic_search tool in Pylon

Phase 3: Hybrid Retrieval + Jargon Awareness (8 tasks)
- Focus: Combining lexical + semantic search with domain jargon boosting
- Key tasks:
  - Populate tsvector for full-text + summary index rows
  - Domain jargon lexicon ("steepeners", "dovish hike", "QT", etc.)
  - Query router for intent classification (lexical/vector/hybrid)
  - Hybrid search with BM25 + vector similarity
  - Reciprocal rank fusion for result merging
  - Per-paper caps to enable multi-hop synthesis
  - Unified search_research tool in Pylon
  - Lightweight citation fields (paper_id + section) for debugging

Phase 4: Caching + Optimization (15 tasks)
- Focus: Token minimization and 2-5s latency target
- Key tasks:
  - Precomputed summaries (paper/theme level; trade-idea optional)
  - Query-level cache with TTL + hash lookup
  - Cache invalidation on new paper ingestion (append-only)
  - Context assembler with token cap (4K-8K) and citations
  - Optional cross-encoder reranker
  - Profiling/optimization for latency target
  - Observability: routing breakdown, latency, cache hit rate, embedding failures
  - Monthly drift monitoring
  - SophiaAgent personality updates
  - Integration tests + documentation
  - Retrieval quality smoke evals (small labeled set)

Integration Points with Your Codebase
- Scrivener for data storage/retrieval
- Pylon for tool gateway
- SophiaAgent for LLM orchestration
- APScheduler for daily/weekly jobs
- SQLAlchemy for ORM
- FastAPI for REST endpoints
- pytest for testing
