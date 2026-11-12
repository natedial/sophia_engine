"""FRED vintages come from ALFRED; sources without an archive are stamped as observed."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from src.db.models import Observation
from src.fetchers import base as base_module
from src.fetchers import fred as fred_module


class _StubFred:
    """Stands in for fredapi.Fred; records each all-releases request."""

    def __init__(self, *args, frame: pd.DataFrame | None = None, **kwargs) -> None:
        self.calls: list[dict] = []
        self.frame = frame if frame is not None else pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-08-01", "2026-09-01", "2026-09-01"]),
                "realtime_start": pd.to_datetime(["2026-09-12", "2026-10-15", "2026-11-13"]),
                "value": [2.9, 3.1, 3.2],
            }
        )

    def get_series_info(self, series_id):
        return pd.Series({"id": series_id, "title": series_id, "frequency_short": "M"})

    def get_series_all_releases(self, series_id, realtime_start=None, realtime_end=None):
        self.calls.append(
            {"series_id": series_id, "realtime_start": realtime_start, "realtime_end": realtime_end}
        )
        return self.frame


@pytest.fixture
def fred(monkeypatch):
    stub = _StubFred()
    monkeypatch.setattr(fred_module, "Fred", lambda *a, **k: stub)
    fetcher = fred_module.FredFetcher()
    return fetcher, stub


def test_fred_rows_carry_alfred_realtime_start(pg_session, fred) -> None:
    fetcher, _ = fred

    rows = fetcher.fetch_observations("CPILFESL", date(2026, 1, 1), date(2026, 12, 31))

    assert rows == [
        {"date": date(2026, 8, 1), "value": 2.9, "realtime_start": date(2026, 9, 12),
         "vintage_source": "alfred"},
        {"date": date(2026, 9, 1), "value": 3.1, "realtime_start": date(2026, 10, 15),
         "vintage_source": "alfred"},
        {"date": date(2026, 9, 1), "value": 3.2, "realtime_start": date(2026, 11, 13),
         "vintage_source": "alfred"},
    ]


def test_fred_rows_outside_window_are_dropped(pg_session, fred) -> None:
    fetcher, _ = fred

    rows = fetcher.fetch_observations("CPILFESL", date(2026, 9, 1), date(2026, 12, 31))

    assert {row["date"] for row in rows} == {date(2026, 9, 1)}


def test_fred_first_fetch_starts_at_window_start(pg_session, fred) -> None:
    fetcher, stub = fred

    fetcher.fetch_observations("CPILFESL", date(2021, 11, 12), date(2026, 11, 12))

    assert stub.calls[-1]["realtime_start"] == "2021-11-12"


def test_fred_incremental_fetch_starts_at_last_stored_vintage(pg_session, fred) -> None:
    fetcher, stub = fred
    series_id = fetcher.ensure_series("CPILFESL", info={"name": "Core CPI"})
    fetcher.store_vintages(
        series_id,
        [{"date": date(2026, 9, 1), "value": 3.1, "realtime_start": date(2026, 10, 15),
          "vintage_source": "alfred"}],
    )

    fetcher.fetch_observations("CPILFESL", date(2021, 11, 12), date(2026, 11, 12))

    assert stub.calls[-1]["realtime_start"] == "2026-10-15"


def test_fetch_and_store_keeps_both_vintages(pg_session, fred) -> None:
    fetcher, _ = fred

    result = fetcher.fetch_and_store("CPILFESL", date(2026, 1, 1), date(2026, 12, 31))

    assert result["status"] == "success"
    assert pg_session.query(Observation).count() == 3


def test_unarchived_rows_are_observed_today_in_eastern_time(pg_session, monkeypatch) -> None:
    """BLS has no vintage archive: a value is known from the day Scrivener sees it."""
    from src.fetchers.bls import BlsFetcher

    # 23:30 UTC on 12 Nov is 18:30 in New York, still 12 Nov.
    monkeypatch.setattr(base_module, "_now", lambda: datetime(2026, 11, 12, 23, 30, tzinfo=UTC))
    fetcher = BlsFetcher()
    series_id = fetcher.ensure_series("CUSR0000SA0L1E", info={"name": "Core CPI"})

    fetcher.store_vintages(series_id, [{"date": date(2026, 9, 1), "value": 3.1}])

    row = pg_session.query(Observation).one()
    assert row.realtime_start == date(2026, 11, 12)
    assert row.vintage_source == "observed"
