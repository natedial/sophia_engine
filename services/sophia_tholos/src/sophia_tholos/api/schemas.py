"""Pydantic request/response models for the Tholos API."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Requests ──────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=100)
    keyword_weight: float = Field(default=0.55, ge=0.0, le=1.0)
    semantic_weight: float = Field(default=0.45, ge=0.0, le=1.0)
    min_lexical_score: float = Field(default=0.05, ge=0.0, le=1.0)
    semantic_tail_mode: str = Field(default="filter")


# ── Responses ─────────────────────────────────────────────────────────────────

class SearchResultItem(BaseModel):
    chunk_id: str
    run_id: str
    source_path: str | None
    page_number: int
    chunk_index: int
    text: str
    keywords: list[dict]
    lexical_score: float
    semantic_score: float
    hybrid_score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    count: int
    query: str


class ChunkResponse(BaseModel):
    chunk_id: str
    run_id: str
    source_path: str | None
    page_number: int
    chunk_index: int
    text: str
    keywords: list[dict]


class SourceItem(BaseModel):
    source_path: str | None
    chunk_count: int


class SourcesResponse(BaseModel):
    sources: list[SourceItem]
    total_sources: int


class HealthResponse(BaseModel):
    status: str
    corpus_available: bool
    chunk_count: int | None = None
    npz_dims: list[int] | None = None
    model_name: str | None = None
