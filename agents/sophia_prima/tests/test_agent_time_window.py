from __future__ import annotations

from datetime import UTC, datetime

from sophia.agent import SophiaAgent

FIXED_NOW = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)


def test_extract_past_two_weeks() -> None:
    result = SophiaAgent._extract_time_window(
        "What are the takes from the past 2 weeks?",
        now=FIXED_NOW,
    )
    assert result == ("2026-03-31", "2026-04-14")


def test_extract_last_30_days() -> None:
    result = SophiaAgent._extract_time_window(
        "Summarize research from the last 30 days.",
        now=FIXED_NOW,
    )
    assert result == ("2026-03-15", "2026-04-14")


def test_extract_previous_3_months() -> None:
    result = SophiaAgent._extract_time_window(
        "Show previous 3 months of desk notes.",
        now=FIXED_NOW,
    )
    assert result == ("2026-01-14", "2026-04-14")


def test_extract_bare_last_week() -> None:
    result = SophiaAgent._extract_time_window(
        "What happened last week?",
        now=FIXED_NOW,
    )
    assert result == ("2026-04-07", "2026-04-14")


def test_extract_bare_past_month() -> None:
    result = SophiaAgent._extract_time_window(
        "Give me takes from the past month.",
        now=FIXED_NOW,
    )
    assert result == ("2026-03-15", "2026-04-14")


def test_extract_this_week() -> None:
    # 2026-04-14 is a Tuesday → Monday is 2026-04-13.
    result = SophiaAgent._extract_time_window(
        "What has this week brought on GDP?",
        now=FIXED_NOW,
    )
    assert result == ("2026-04-13", "2026-04-14")


def test_extract_this_month() -> None:
    result = SophiaAgent._extract_time_window(
        "Takes from this month on Iran?",
        now=FIXED_NOW,
    )
    assert result == ("2026-04-01", "2026-04-14")


def test_extract_ytd() -> None:
    result = SophiaAgent._extract_time_window(
        "YTD research on labor markets.",
        now=FIXED_NOW,
    )
    assert result == ("2026-01-01", "2026-04-14")


def test_extract_year_to_date_phrase() -> None:
    result = SophiaAgent._extract_time_window(
        "Year to date research on labor markets.",
        now=FIXED_NOW,
    )
    assert result == ("2026-01-01", "2026-04-14")


def test_no_temporal_phrase_returns_none() -> None:
    assert (
        SophiaAgent._extract_time_window(
            "What do we think about GDP impact?",
            now=FIXED_NOW,
        )
        is None
    )


def test_empty_message_returns_none() -> None:
    assert SophiaAgent._extract_time_window("", now=FIXED_NOW) is None


def test_default_now_uses_current_utc() -> None:
    # When now is not passed, the function should still return a valid window
    # whose end date equals today (UTC). This keeps production calls simple.
    result = SophiaAgent._extract_time_window("past 7 days")
    assert result is not None
    date_from, date_to = result
    today = datetime.now(UTC).date().isoformat()
    assert date_to == today
