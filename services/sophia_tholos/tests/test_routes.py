"""Tests for sophia_tholos API routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from sophia_tholos.search.engine import SearchResult


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.chunk_count = 100
    engine.npz_dims = (100, 384)
    engine.model_name = "all-MiniLM-L6-v2"
    engine.semantic_enabled = True
    engine.semantic_available = True
    engine.last_semantic_error = None
    engine.search.return_value = [
        SearchResult(
            chunk_id="c1",
            run_id="r1",
            source_path="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Test chunk text",
            keywords=[{"keyword": "test", "score": 1.0}],
            lexical_score=0.8,
            semantic_score=0.7,
            hybrid_score=0.75,
        )
    ]
    engine.get_chunk.return_value = {
        "run_id": "r1",
        "source_path": "test.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": "Test chunk text",
        "keywords": [{"keyword": "test", "score": 1.0}],
    }
    engine.list_sources.return_value = [
        {"source_path": "test.pdf", "chunk_count": 50},
        {"source_path": "other.pdf", "chunk_count": 50},
    ]
    return engine


@pytest.fixture
def client(mock_engine):
    from sophia_tholos.main import app

    with patch("sophia_tholos.api.routes.get_engine", return_value=mock_engine), \
         patch("sophia_tholos.main.Settings"), \
         patch("sophia_tholos.main.init_engine"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture
def client_no_corpus():
    from sophia_tholos.main import app

    with patch("sophia_tholos.api.routes.get_engine", return_value=None), \
         patch("sophia_tholos.main.Settings"), \
         patch("sophia_tholos.main.init_engine"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestHealth:
    def test_health_with_corpus(self, client, mock_engine):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["corpus_available"] is True
        assert data["chunk_count"] == 100
        assert data["npz_dims"] == [100, 384]
        assert data["semantic_enabled"] is True
        assert data["semantic_available"] is True

    def test_health_no_corpus(self, client_no_corpus):
        resp = client_no_corpus.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["corpus_available"] is False

    def test_ready_with_corpus(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["corpus_available"] is True

    def test_ready_no_corpus(self, client_no_corpus):
        resp = client_no_corpus.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Corpus not loaded"


class TestSearch:
    def test_search_success(self, client, mock_engine):
        resp = client.post("/search", json={"query": "test query", "limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["chunk_id"] == "c1"
        assert data["query"] == "test query"
        mock_engine.search.assert_called_once()

    def test_search_no_corpus(self, client_no_corpus):
        resp = client_no_corpus.post("/search", json={"query": "test"})
        assert resp.status_code == 503

    def test_search_rejects_invalid_date_window(self, client):
        resp = client.post(
            "/search",
            json={
                "query": "ieepa",
                "date_from": "2026-02-24",
                "date_to": "2026-02-19",
            },
        )
        assert resp.status_code == 422

    def test_search_forwards_scope_filters(self, client, mock_engine):
        resp = client.post(
            "/search",
            json={
                "query": "ieepa tariffs",
                "run_id": "run-a",
                "run_ids": ["run-a", "run-b"],
                "source_paths": ["supabase:150"],
                "exclude_source_paths": ["supabase:999"],
                "source_path_prefix": "supabase:",
                "source_path_contains": "150",
                "min_page_number": 2,
                "max_page_number": 20,
                "max_per_source": 2,
                "date_from": "2026-02-19",
                "date_to": "2026-02-24",
            },
        )
        assert resp.status_code == 200
        _, kwargs = mock_engine.search.call_args
        assert kwargs["run_id"] == "run-a"
        assert kwargs["run_ids"] == ["run-a", "run-b"]
        assert kwargs["source_paths"] == ["supabase:150"]
        assert kwargs["exclude_source_paths"] == ["supabase:999"]
        assert kwargs["source_path_prefix"] == "supabase:"
        assert kwargs["source_path_contains"] == "150"
        assert kwargs["min_page_number"] == 2
        assert kwargs["max_page_number"] == 20
        assert kwargs["max_per_source"] == 2
        assert kwargs["date_from"] == "2026-02-19 00:00:00"
        assert kwargs["date_to"] == "2026-02-24 23:59:59"


class TestGetChunk:
    def test_get_chunk_success(self, client, mock_engine):
        resp = client.get("/chunk/c1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunk_id"] == "c1"
        assert data["text"] == "Test chunk text"

    def test_get_chunk_not_found(self, client, mock_engine):
        mock_engine.get_chunk.return_value = None
        resp = client.get("/chunk/missing")
        assert resp.status_code == 404

    def test_get_chunk_no_corpus(self, client_no_corpus):
        resp = client_no_corpus.get("/chunk/c1")
        assert resp.status_code == 503


class TestSources:
    def test_list_sources(self, client, mock_engine):
        resp = client.get("/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_sources"] == 2
        assert data["sources"][0]["source_path"] == "test.pdf"

    def test_sources_no_corpus(self, client_no_corpus):
        resp = client_no_corpus.get("/sources")
        assert resp.status_code == 503
