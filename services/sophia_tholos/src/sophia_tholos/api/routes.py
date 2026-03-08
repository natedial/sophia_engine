"""API endpoints for sophia_tholos."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from sophia_tholos.api.schemas import (
    ChunkResponse,
    HealthResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SourceItem,
    SourcesResponse,
)
from sophia_tholos.core.corpus import get_engine

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    engine = get_engine()
    if engine is None:
        return HealthResponse(status="ok", corpus_available=False)
    dims = engine.npz_dims
    return HealthResponse(
        status="ok",
        corpus_available=True,
        chunk_count=engine.chunk_count,
        npz_dims=list(dims) if dims else None,
        model_name=engine.model_name,
    )


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    engine = get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Corpus not loaded")

    results = engine.search(
        query=req.query,
        limit=req.limit,
        run_id=req.run_id,
        run_ids=req.run_ids,
        source_paths=req.source_paths,
        exclude_source_paths=req.exclude_source_paths,
        source_path_prefix=req.source_path_prefix,
        source_path_contains=req.source_path_contains,
        min_page_number=req.min_page_number,
        max_page_number=req.max_page_number,
        max_per_source=req.max_per_source,
        date_from=req.date_from,
        date_to=req.date_to,
        keyword_weight=req.keyword_weight,
        semantic_weight=req.semantic_weight,
        min_lexical_score=req.min_lexical_score,
        semantic_tail_mode=req.semantic_tail_mode,
    )
    items = [SearchResultItem(**asdict(r)) for r in results]
    return SearchResponse(results=items, count=len(items), query=req.query)


@router.get("/chunk/{chunk_id}", response_model=ChunkResponse)
async def get_chunk(chunk_id: str) -> ChunkResponse:
    engine = get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Corpus not loaded")

    chunk = engine.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(status_code=404, detail=f"Chunk not found: {chunk_id}")

    return ChunkResponse(
        chunk_id=chunk_id,
        run_id=chunk["run_id"],
        source_path=chunk["source_path"],
        page_number=chunk["page_number"],
        chunk_index=chunk["chunk_index"],
        text=chunk["text"],
        keywords=chunk["keywords"],
    )


@router.get("/sources", response_model=SourcesResponse)
async def list_sources() -> SourcesResponse:
    engine = get_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="Corpus not loaded")

    sources = engine.list_sources()
    items = [SourceItem(**s) for s in sources]
    return SourcesResponse(sources=items, total_sources=len(items))
