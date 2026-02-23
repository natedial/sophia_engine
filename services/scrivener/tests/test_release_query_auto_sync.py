"""Tests for release query resilience behavior."""

from datetime import date
from types import SimpleNamespace

from src.query.releases import ReleaseQuery


def _release_row(
    release_date: date,
    *,
    release_id: int = 10,
    fred_release_id: int = 10,
    name: str = "Consumer Price Index",
    press_release: bool = True,
):
    release = SimpleNamespace(
        id=release_id,
        name=name,
        fred_release_id=fred_release_id,
        link=None,
        press_release=press_release,
    )
    rd = SimpleNamespace(release_date=release_date, release_id=release_id)
    return rd, release


def test_get_upcoming_retries_after_auto_sync(monkeypatch):
    """When first query is empty, upcoming should sync then retry once."""
    calls = {"query": 0}

    def fake_query(_start, _end, *, press_release_only=False, limit=None):
        calls["query"] += 1
        if calls["query"] == 1:
            return []
        return [_release_row(date(2026, 3, 3), press_release=not press_release_only)]

    monkeypatch.setattr(
        ReleaseQuery,
        "_query_release_rows",
        staticmethod(fake_query),
    )
    monkeypatch.setattr(
        ReleaseQuery,
        "_auto_sync_release_calendar",
        staticmethod(lambda days_ahead: True),
    )

    results = ReleaseQuery.get_upcoming(days=7)

    assert calls["query"] == 2
    assert len(results) == 1
    assert results[0]["release_date"] == "2026-03-03"


def test_get_upcoming_no_retry_when_sync_unavailable(monkeypatch):
    """If sync cannot run, upcoming should return empty without a second query."""
    calls = {"query": 0}

    def fake_query(_start, _end, *, press_release_only=False, limit=None):
        calls["query"] += 1
        return []

    monkeypatch.setattr(
        ReleaseQuery,
        "_query_release_rows",
        staticmethod(fake_query),
    )
    monkeypatch.setattr(
        ReleaseQuery,
        "_auto_sync_release_calendar",
        staticmethod(lambda days_ahead: False),
    )

    results = ReleaseQuery.get_upcoming(days=7)

    assert calls["query"] == 1
    assert results == []


def test_get_summary_retries_after_auto_sync(monkeypatch):
    """Summary should use synced rows when initial range query is empty."""
    calls = {"query": 0}

    def fake_query(_start, _end, *, press_release_only=False, limit=None):
        calls["query"] += 1
        if calls["query"] == 1:
            return []
        return [
            _release_row(date(2026, 3, 3), fred_release_id=10, press_release=True),
            _release_row(date(2026, 3, 3), fred_release_id=11, press_release=False),
            _release_row(date(2026, 3, 4), fred_release_id=12, press_release=True),
        ]

    monkeypatch.setattr(
        ReleaseQuery,
        "_query_release_rows",
        staticmethod(fake_query),
    )
    monkeypatch.setattr(
        ReleaseQuery,
        "_auto_sync_release_calendar",
        staticmethod(lambda days_ahead: True),
    )

    summary = ReleaseQuery.get_summary(days=7)

    assert calls["query"] == 2
    assert summary["total_releases"] == 3
    assert summary["press_releases"] == 2
    assert summary["by_date"] == {"2026-03-03": 2, "2026-03-04": 1}


def test_format_rows_handles_missing_release_metadata():
    """Rows should still format when release_dates exists without releases row."""
    rd = SimpleNamespace(release_date=date(2026, 3, 6), release_id=999)
    rows = [(rd, None)]

    results = ReleaseQuery._format_release_rows(rows)

    assert len(results) == 1
    assert results[0]["name"] == "Release 999"
    assert results[0]["fred_release_id"] == 999
    assert results[0]["press_release"] is False
