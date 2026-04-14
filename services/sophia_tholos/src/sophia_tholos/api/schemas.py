"""Pydantic request/response models for the Tholos API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Self

from pydantic import BaseModel, Field
from pydantic import model_validator


# ── Requests ──────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=100)
    keyword_weight: float = Field(default=0.55, ge=0.0, le=1.0)
    semantic_weight: float = Field(default=0.45, ge=0.0, le=1.0)
    min_lexical_score: float = Field(default=0.05, ge=0.0, le=1.0)
    semantic_tail_mode: str = Field(default="filter")
    run_id: str | None = None
    run_ids: list[str] | None = None
    source_paths: list[str] | None = None
    exclude_source_paths: list[str] | None = None
    source_path_prefix: str | None = None
    source_path_contains: str | None = None
    min_page_number: int | None = Field(default=None, ge=1)
    max_page_number: int | None = Field(default=None, ge=1)
    max_per_source: int | None = Field(default=None, ge=1, le=20)
    date_from: str | None = None
    date_to: str | None = None

    @model_validator(mode="after")
    def validate_page_window(self) -> Self:
        if (
            self.min_page_number is not None
            and self.max_page_number is not None
            and self.min_page_number > self.max_page_number
        ):
            raise ValueError("min_page_number cannot be greater than max_page_number")
        start = _parse_window_ts(self.date_from, end_of_day=False)
        end = _parse_window_ts(self.date_to, end_of_day=True)
        if start and end and start > end:
            raise ValueError("date_from cannot be greater than date_to")
        self.date_from = start
        self.date_to = end
        return self


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
    semantic_enabled: bool | None = None
    semantic_available: bool | None = None
    semantic_error: str | None = None


def _parse_window_ts(value: str | None, *, end_of_day: bool) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None

    has_explicit_time = ":" in cleaned
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid datetime value '{value}'") from exc

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if end_of_day and not has_explicit_time:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=0)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")
