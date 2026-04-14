from __future__ import annotations

from datetime import UTC, datetime

from sophia.agent import SophiaAgent


FIXED_NOW = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)


def test_prefetch_passes_date_window_when_temporal_phrase_present() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "Based on research in our corpus from the past 2 weeks, takes on Iran?",
        now=FIXED_NOW,
    )
    assert result["date_from"] == "2026-03-31"
    assert result["date_to"] == "2026-04-14"
    assert result["limit"] == 8
    assert result["keyword_weight"] == 0.65
    assert result["semantic_weight"] == 0.35


def test_prefetch_omits_date_window_when_no_temporal_phrase() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "What do we think about GDP?",
        now=FIXED_NOW,
    )
    assert "date_from" not in result
    assert "date_to" not in result
    assert result["query"] == "What do we think about GDP?"


def test_prefetch_recall_mode_keeps_date_window() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "past 30 days of labor research",
        recall_mode=True,
        now=FIXED_NOW,
    )
    assert result["date_from"] == "2026-03-15"
    assert result["date_to"] == "2026-04-14"
    assert result["keyword_weight"] == 0.45
    assert result["semantic_weight"] == 0.55
    assert result["semantic_tail_mode"] == "keep"


def test_prefetch_query_override_uses_override_but_time_window_from_user_message() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "past 2 weeks, Iran conflict labor impact",
        query_override="iran labor",
        now=FIXED_NOW,
    )
    assert result["query"] == "iran labor"
    assert result["date_from"] == "2026-03-31"
    assert result["date_to"] == "2026-04-14"


def test_prefetch_this_week_window() -> None:
    result = SophiaAgent._build_research_prefetch_input(
        "what has this week brought on GDP",
        now=FIXED_NOW,
    )
    # 2026-04-14 is Tuesday; Monday is 2026-04-13
    assert result["date_from"] == "2026-04-13"
    assert result["date_to"] == "2026-04-14"
