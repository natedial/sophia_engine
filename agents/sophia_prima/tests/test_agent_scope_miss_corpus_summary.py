from __future__ import annotations

import json
from typing import Any

import pytest

from sophia.agent import SophiaAgent


class _StubPylonResult:
    def __init__(self, *, success: bool, content: str) -> None:
        self.success = success
        self._content = content

    def to_content(self) -> str:
        return self._content


class _StubPylon:
    def __init__(self, payload: dict[str, Any] | None, *, success: bool = True) -> None:
        self._payload = payload
        self._success = success
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute_tool(self, name: str, payload: dict[str, Any]):
        self.calls.append((name, payload))
        content = json.dumps(self._payload) if self._payload is not None else "{}"
        return _StubPylonResult(success=self._success, content=content)


def test_scope_miss_response_includes_corpus_summary_when_provided() -> None:
    response = SophiaAgent._build_local_research_scope_miss_response(
        user_message="takes on Iran conflict past 2 weeks",
        fallback_reason="local_research_prefetch_returned_no_hits",
        corpus_summary="Corpus currently indexes 42 sources (e.g. fed_speeches, bls_reports).",
    )
    assert "42 sources" in response
    assert "fed_speeches" in response


def test_scope_miss_response_omits_summary_line_when_none() -> None:
    response = SophiaAgent._build_local_research_scope_miss_response(
        user_message="takes on Iran conflict past 2 weeks",
        fallback_reason="local_research_prefetch_returned_no_hits",
        corpus_summary=None,
    )
    assert "Corpus currently indexes" not in response
    assert "widen the corpus scope or switch to web" in response


def test_scope_miss_response_works_for_prefetch_failed_reason() -> None:
    response = SophiaAgent._build_local_research_scope_miss_response(
        user_message="takes on Iran conflict past 2 weeks",
        fallback_reason="local_research_prefetch_failed",
        corpus_summary="Corpus currently indexes 7 sources.",
    )
    assert "couldn't complete the corpus check" in response
    assert "7 sources" in response


@pytest.mark.asyncio
async def test_fetch_corpus_inventory_summary_returns_formatted_string() -> None:
    agent = object.__new__(SophiaAgent)
    agent.pylon = _StubPylon(
        {
            "sources": [
                {"source_path": "fed_speeches/powell_2026_04_10.pdf", "chunk_count": 12},
                {"source_path": "bls_reports/jobs_2026_04.pdf", "chunk_count": 7},
                {"source_path": "research/gdp_outlook_q2.pdf", "chunk_count": 5},
            ]
        }
    )
    summary = await agent._fetch_corpus_inventory_summary()
    assert summary is not None
    assert "3 sources" in summary
    assert "fed_speeches" in summary


@pytest.mark.asyncio
async def test_fetch_corpus_inventory_summary_returns_none_on_tool_failure() -> None:
    agent = object.__new__(SophiaAgent)
    agent.pylon = _StubPylon(None, success=False)
    summary = await agent._fetch_corpus_inventory_summary()
    assert summary is None


@pytest.mark.asyncio
async def test_fetch_corpus_inventory_summary_returns_none_when_empty() -> None:
    agent = object.__new__(SophiaAgent)
    agent.pylon = _StubPylon({"sources": []})
    summary = await agent._fetch_corpus_inventory_summary()
    assert summary is None
