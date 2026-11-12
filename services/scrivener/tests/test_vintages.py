"""Observations are insert-only: each vintage of a value is its own row."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.db.models import Observation
from src.fetchers.base import BaseFetcher
from src.query.series import SeriesQuery


class _Fetcher(BaseFetcher):
    source_name = "TEST"

    def fetch_series_info(self, external_id: str) -> dict[str, Any]:
        return {"name": external_id}

    def fetch_observations(self, external_id, start_date=None, end_date=None):
        return []


def _series(fetcher: _Fetcher, external_id: str = "X") -> int:
    return fetcher.ensure_series(external_id, info={"name": external_id})


def _row(day: date, value: float, known: date) -> dict:
    return {
        "date": day,
        "value": value,
        "realtime_start": known,
        "vintage_source": "alfred",
    }


def test_first_value_is_stored(pg_session) -> None:
    fetcher = _Fetcher()
    sid = _series(fetcher)

    result = fetcher.store_vintages(sid, [_row(date(2026, 9, 1), 3.1, date(2026, 10, 15))])

    assert result == {"new_dates": 1, "revisions": 0, "unchanged": 0}
    assert pg_session.query(Observation).count() == 1


def test_revised_value_adds_a_row(pg_session) -> None:
    fetcher = _Fetcher()
    sid = _series(fetcher)
    fetcher.store_vintages(sid, [_row(date(2026, 9, 1), 3.1, date(2026, 10, 15))])

    result = fetcher.store_vintages(sid, [_row(date(2026, 9, 1), 3.2, date(2026, 11, 13))])

    assert result == {"new_dates": 0, "revisions": 1, "unchanged": 0}
    assert pg_session.query(Observation).count() == 2


def test_unchanged_value_is_not_a_new_vintage(pg_session) -> None:
    """ALFRED reports an unrevised value with the requested realtime_start."""
    fetcher = _Fetcher()
    sid = _series(fetcher)
    fetcher.store_vintages(sid, [_row(date(2026, 9, 1), 3.1, date(2026, 10, 15))])

    result = fetcher.store_vintages(sid, [_row(date(2026, 9, 1), 3.1, date(2026, 11, 13))])

    assert result == {"new_dates": 0, "revisions": 0, "unchanged": 1}
    assert pg_session.query(Observation).count() == 1


def test_same_vintage_twice_is_unchanged(pg_session) -> None:
    fetcher = _Fetcher()
    sid = _series(fetcher)
    row = _row(date(2026, 9, 1), 3.1, date(2026, 10, 15))
    fetcher.store_vintages(sid, [row])

    result = fetcher.store_vintages(sid, [row])

    assert result == {"new_dates": 0, "revisions": 0, "unchanged": 1}


def test_row_without_realtime_start_is_observed_today(pg_session) -> None:
    fetcher = _Fetcher()
    sid = _series(fetcher)

    fetcher.store_vintages(sid, [{"date": date(2026, 9, 1), "value": 3.1}])

    row = pg_session.query(Observation).one()
    assert row.vintage_source == "observed"
    assert row.realtime_start is not None


def test_readers_return_one_row_per_date(pg_session) -> None:
    fetcher = _Fetcher()
    sid = _series(fetcher)
    fetcher.store_vintages(
        sid,
        [
            _row(date(2026, 8, 1), 2.9, date(2026, 9, 12)),
            _row(date(2026, 9, 1), 3.1, date(2026, 10, 15)),
        ],
    )
    fetcher.store_vintages(sid, [_row(date(2026, 9, 1), 3.2, date(2026, 11, 13))])

    observations = SeriesQuery.get_observations(
        "X", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    latest = SeriesQuery.get_latest("X")
    change = SeriesQuery.get_change("X", periods=1, pct=False)

    assert observations == [
        {"date": "2026-08-01", "value": 2.9},
        {"date": "2026-09-01", "value": 3.2},
    ]
    assert latest["value"] == 3.2
    assert round(change["change"], 6) == round(3.2 - 2.9, 6)
