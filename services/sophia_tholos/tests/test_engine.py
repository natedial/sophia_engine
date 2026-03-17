"""Tests for source_date-aware filtering in the Tholos search engine."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sophia_tholos.search.engine import HybridSearchEngine, SearchResult, _rerank_search_results


def _build_test_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                source_path TEXT,
                source_date TEXT,
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE chunks_fts
            USING fts5(chunk_id UNINDEXED, text, tokenize='unicode61')
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE keyword_fts
            USING fts5(chunk_id UNINDEXED, terms, tokenize='unicode61')
            """
        )

        rows = [
            (
                "chunk-source-date",
                "run-1",
                "supabase:1",
                "2026-03-07",
                1,
                0,
                "Jobs report says payroll growth slowed materially.",
                "[]",
                "hash-1",
                "2026-03-09 04:00:00",
            ),
            (
                "chunk-created-at",
                "run-2",
                "supabase:2",
                "2026-03-02",
                1,
                0,
                "Jobs report says payroll growth slowed materially.",
                "[]",
                "hash-2",
                "2026-03-07 04:00:00",
            ),
            (
                "chunk-fallback-created-at",
                "run-3",
                "supabase:3",
                None,
                1,
                0,
                "Jobs report says payroll growth slowed materially.",
                "[]",
                "hash-3",
                "2026-03-07 10:00:00",
            ),
        ]

        conn.executemany(
            """
            INSERT INTO chunks (
                chunk_id, run_id, source_path, source_date, page_number, chunk_index,
                text, keywords_json, text_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.executemany(
            "INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)",
            [(row[0], row[6]) for row in rows],
        )
        conn.executemany(
            "INSERT INTO keyword_fts (chunk_id, terms) VALUES (?, ?)",
            [(row[0], "jobs report payroll growth") for row in rows],
        )


def test_search_filters_on_source_date_before_created_at(tmp_path: Path) -> None:
    db_path = tmp_path / "chunks.sqlite"
    _build_test_db(db_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=None)

    results = engine.search(
        query="jobs report",
        limit=10,
        date_from="2026-03-06 00:00:00",
        date_to="2026-03-08 23:59:59",
        keyword_weight=1.0,
        semantic_weight=0.0,
    )

    result_ids = [result.chunk_id for result in results]
    assert "chunk-source-date" in result_ids
    assert "chunk-created-at" not in result_ids


def test_search_falls_back_to_created_at_when_source_date_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "chunks.sqlite"
    _build_test_db(db_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=None)

    results = engine.search(
        query="jobs report",
        limit=10,
        date_from="2026-03-06 00:00:00",
        date_to="2026-03-08 23:59:59",
        keyword_weight=1.0,
        semantic_weight=0.0,
    )

    result_ids = [result.chunk_id for result in results]
    assert "chunk-fallback-created-at" in result_ids


def test_reranker_promotes_phrase_and_query_coverage_matches() -> None:
    results = [
        SearchResult(
            chunk_id="broad-match",
            run_id="run-1",
            source_path="macro/general.pdf",
            page_number=1,
            chunk_index=0,
            text="Tariffs could have broad macro fallout with uncertain timing.",
            keywords=[],
            lexical_score=0.72,
            semantic_score=0.78,
            hybrid_score=0.75,
        ),
        SearchResult(
            chunk_id="precise-match",
            run_id="run-1",
            source_path="macro/supreme-court.pdf",
            page_number=2,
            chunk_index=0,
            text=(
                "Reports since last Friday on Supreme Court tariff fallout suggest "
                "import costs may ease faster than expected."
            ),
            keywords=[],
            lexical_score=0.69,
            semantic_score=0.76,
            hybrid_score=0.73,
        ),
    ]

    reranked = _rerank_search_results(
        "supreme court tariff fallout last friday",
        results,
    )

    assert reranked[0].chunk_id == "precise-match"
