from __future__ import annotations

import json

import pytest

from pylon.tools.tholos import (
    TholosToolExecutor,
    _coerce_float,
    _coerce_int,
    _coerce_optional_int,
    _coerce_optional_str,
    _coerce_string_list,
    _coerce_tail_mode,
)


class _FakeTholosClient:
    def __init__(self) -> None:
        self.search_calls: list[dict] = []

    async def search(
        self,
        query: str,
        limit: int = 10,
        keyword_weight: float | None = None,
        semantic_weight: float | None = None,
        min_lexical_score: float | None = None,
        semantic_tail_mode: str | None = None,
        run_id: str | None = None,
        run_ids: list[str] | None = None,
        source_paths: list[str] | None = None,
        exclude_source_paths: list[str] | None = None,
        source_path_prefix: str | None = None,
        source_path_contains: str | None = None,
        min_page_number: int | None = None,
        max_page_number: int | None = None,
        max_per_source: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        self.search_calls.append(
            {
                "query": query,
                "limit": limit,
                "keyword_weight": keyword_weight,
                "semantic_weight": semantic_weight,
                "min_lexical_score": min_lexical_score,
                "semantic_tail_mode": semantic_tail_mode,
                "run_id": run_id,
                "run_ids": run_ids,
                "source_paths": source_paths,
                "exclude_source_paths": exclude_source_paths,
                "source_path_prefix": source_path_prefix,
                "source_path_contains": source_path_contains,
                "min_page_number": min_page_number,
                "max_page_number": max_page_number,
                "max_per_source": max_per_source,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return {"results": [], "count": 0, "query": query}


def test_coerce_helpers_apply_bounds_and_defaults() -> None:
    assert _coerce_int("200", default=10, minimum=1, maximum=100) == 100
    assert _coerce_int("x", default=10, minimum=1, maximum=100) == 10

    assert _coerce_float("1.7", default=0.5, minimum=0.0, maximum=1.0) == 1.0
    assert _coerce_float("-0.2", default=0.5, minimum=0.0, maximum=1.0) == 0.0
    assert _coerce_float("bad", default=0.5, minimum=0.0, maximum=1.0) == 0.5

    assert _coerce_tail_mode("allow", default="demote") == "allow"
    assert _coerce_tail_mode("invalid", default="demote") == "demote"
    assert _coerce_tail_mode(None, default="demote") == "demote"
    assert _coerce_optional_int("3", minimum=1, maximum=10) == 3
    assert _coerce_optional_int("x", minimum=1, maximum=10) is None
    assert _coerce_optional_str("  abc  ") == "abc"
    assert _coerce_optional_str("   ") is None
    assert _coerce_string_list([" a ", "", "b", "a"], max_items=10) == ["a", "b"]
    assert _coerce_string_list("bad", max_items=10) is None


@pytest.mark.asyncio
async def test_search_research_uses_sanitized_precision_defaults() -> None:
    client = _FakeTholosClient()
    executor = TholosToolExecutor(client)

    result = await executor.execute(
        "search_research",
        {
            "query": "tariff welfare effects",
            "limit": "200",
            "keyword_weight": "2.0",
            "semantic_weight": "-1",
            "min_lexical_score": "bad",
            "semantic_tail_mode": "weird",
        },
    )

    assert result.success is True
    parsed = json.loads(result.data)
    assert parsed["query"] == "tariff welfare effects"
    assert client.search_calls
    call = client.search_calls[0]
    assert call["limit"] == 100
    assert call["keyword_weight"] == 1.0
    assert call["semantic_weight"] == 0.0
    assert call["min_lexical_score"] == 0.08
    assert call["semantic_tail_mode"] == "demote"


@pytest.mark.asyncio
async def test_search_research_accepts_scope_parameters() -> None:
    client = _FakeTholosClient()
    executor = TholosToolExecutor(client)

    result = await executor.execute(
        "search_research",
        {
            "query": "ieepa tariffs",
            "run_id": " run-1 ",
            "run_ids": ["run-1", "run-2", ""],
            "source_paths": ["supabase:150", "supabase:181"],
            "exclude_source_paths": ["supabase:999", "supabase:999"],
            "source_path_prefix": " supabase: ",
            "source_path_contains": " 150 ",
            "min_page_number": "2",
            "max_page_number": "20",
            "max_per_source": "3",
            "date_from": "2026-02-19",
            "date_to": "2026-02-24",
        },
    )

    assert result.success is True
    call = client.search_calls[0]
    assert call["run_id"] == "run-1"
    assert call["run_ids"] == ["run-1", "run-2"]
    assert call["source_paths"] == ["supabase:150", "supabase:181"]
    assert call["exclude_source_paths"] == ["supabase:999"]
    assert call["source_path_prefix"] == "supabase:"
    assert call["source_path_contains"] == "150"
    assert call["min_page_number"] == 2
    assert call["max_page_number"] == 20
    assert call["max_per_source"] == 3
    assert call["date_from"] == "2026-02-19"
    assert call["date_to"] == "2026-02-24"
