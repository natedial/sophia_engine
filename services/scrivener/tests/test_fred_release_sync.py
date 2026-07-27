"""Tests for FRED release calendar pagination and safe reconciliation."""

from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Release, ReleaseDate
from src.fetchers import fred as fred_module
from src.fetchers.fred import FredFetcher


def _make_fetcher() -> FredFetcher:
    fetcher = FredFetcher.__new__(FredFetcher)
    fetcher.settings = SimpleNamespace(
        fred_api_key="test-key",
        default_lookback_years=5,
    )
    fetcher._source_id = None
    return fetcher


def _release_date_payload(
    fred_release_id: int,
    release_name: str,
    release_date: date,
) -> dict[str, object]:
    return {
        "fred_release_id": fred_release_id,
        "release_name": release_name,
        "release_date": release_date,
    }


def _make_session_scope():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Release.__table__.create(engine)
    ReleaseDate.__table__.create(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def session_scope():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return session_scope


def test_fetch_release_dates_paginates_across_multiple_pages(monkeypatch) -> None:
    """Specific-release fetch should collect every page until the reported count is reached."""
    fetcher = _make_fetcher()
    today = date.today()

    def fake_api_request(endpoint: str, params: dict[str, str]) -> dict[str, object]:
        assert endpoint == "release/dates"
        assert params["release_id"] == "50"
        if params["offset"] == "0":
            return {
                "count": 3,
                "limit": 2,
                "offset": 0,
                "release_dates": [
                    {
                        "release_id": 10,
                        "release_name": "Employment Situation",
                        "date": (today + timedelta(days=7)).isoformat(),
                    },
                    {
                        "release_id": 11,
                        "release_name": "ADP National Employment Report",
                        "date": (today + timedelta(days=6)).isoformat(),
                    },
                ],
            }
        return {
            "count": 3,
            "limit": 2,
            "offset": 2,
            "release_dates": [
                {
                    "release_id": 12,
                    "release_name": "Consumer Price Index",
                    "date": (today + timedelta(days=12)).isoformat(),
                }
            ],
        }

    monkeypatch.setattr(fetcher, "_api_request", fake_api_request)

    result = fetcher.fetch_release_dates(release_id=50, days_ahead=90)

    assert result["complete"] is True
    assert result["fetched_count"] == 3
    assert result["expected_count"] == 3
    assert [row["fred_release_id"] for row in result["release_dates"]] == [10, 11, 12]


def test_fetch_release_dates_marks_result_incomplete_when_pagination_breaks(monkeypatch) -> None:
    """Specific-release fetch should preserve partial rows but mark the snapshot degraded."""
    fetcher = _make_fetcher()
    today = date.today()

    def fake_api_request(endpoint: str, params: dict[str, str]) -> dict[str, object]:
        assert endpoint == "release/dates"
        assert params["release_id"] == "50"
        if params["offset"] == "0":
            return {
                "count": 3,
                "limit": 2,
                "offset": 0,
                "release_dates": [
                    {
                        "release_id": 10,
                        "release_name": "Employment Situation",
                        "date": (today + timedelta(days=7)).isoformat(),
                    },
                    {
                        "release_id": 11,
                        "release_name": "ADP National Employment Report",
                        "date": (today + timedelta(days=6)).isoformat(),
                    },
                ],
            }
        raise RuntimeError("page 2 failed")

    monkeypatch.setattr(fetcher, "_api_request", fake_api_request)

    result = fetcher.fetch_release_dates(release_id=50, days_ahead=90)

    assert result["complete"] is False
    assert result["fetched_count"] == 2
    assert result["expected_count"] == 3
    assert result["degraded_reason"] == "request_failed:RuntimeError"


def test_fetch_release_dates_collects_all_release_windows(monkeypatch) -> None:
    """All-release fetches should split the horizon into smaller windows."""
    fetcher = _make_fetcher()
    today = date.today()
    calls: list[tuple[str, str, int]] = []

    def fake_collect_paginated(endpoint: str, *, params, item_key: str, limit: int):
        assert endpoint == "releases/dates"
        assert item_key == "release_dates"
        calls.append((params["realtime_start"], params["realtime_end"], limit))
        if params["realtime_start"] == today.isoformat():
            return {
                "items": [
                    {
                        "release_id": 10,
                        "release_name": "Employment Situation",
                        "date": (today + timedelta(days=1)).isoformat(),
                    }
                ],
                "fetched_count": 1,
                "expected_count": 1,
                "page_count": 1,
                "complete": True,
                "degraded_reason": None,
            }
        return {
            "items": [
                {
                    "release_id": 11,
                    "release_name": "ADP National Employment Report",
                    "date": (today + timedelta(days=8)).isoformat(),
                }
            ],
            "fetched_count": 1,
            "expected_count": 1,
            "page_count": 1,
            "complete": True,
            "degraded_reason": None,
        }

    monkeypatch.setattr(fetcher, "_collect_paginated", fake_collect_paginated)

    result = fetcher.fetch_release_dates(days_ahead=10)

    assert result["complete"] is True
    assert result["fetched_count"] == 2
    assert result["expected_count"] == 2
    assert [row["fred_release_id"] for row in result["release_dates"]] == [10, 11]
    assert calls == [
        (today.isoformat(), (today + timedelta(days=6)).isoformat(), 250),
        ((today + timedelta(days=7)).isoformat(), (today + timedelta(days=10)).isoformat(), 250),
    ]


def test_fetch_release_dates_marks_windowed_result_incomplete_when_chunk_degrades(monkeypatch) -> None:
    """A degraded window should keep fetched rows but mark the full snapshot degraded."""
    fetcher = _make_fetcher()
    today = date.today()

    def fake_collect_paginated(endpoint: str, *, params, item_key: str, limit: int):
        assert endpoint == "releases/dates"
        if params["realtime_start"] == today.isoformat():
            return {
                "items": [
                    {
                        "release_id": 10,
                        "release_name": "Employment Situation",
                        "date": (today + timedelta(days=1)).isoformat(),
                    }
                ],
                "fetched_count": 1,
                "expected_count": 1,
                "page_count": 1,
                "complete": True,
                "degraded_reason": None,
            }
        return {
            "items": [
                {
                    "release_id": 11,
                    "release_name": "ADP National Employment Report",
                    "date": (today + timedelta(days=8)).isoformat(),
                }
            ],
            "fetched_count": 1,
            "expected_count": 2,
            "page_count": 1,
            "complete": False,
            "degraded_reason": "request_failed:The read operation timed out",
        }

    monkeypatch.setattr(fetcher, "_collect_paginated", fake_collect_paginated)

    result = fetcher.fetch_release_dates(days_ahead=10)

    assert result["complete"] is False
    assert result["fetched_count"] == 2
    assert result["expected_count"] == 3
    assert (
        result["degraded_reason"]
        == "window_degraded:"
        f"{(today + timedelta(days=7)).isoformat()}:{(today + timedelta(days=10)).isoformat()}:"
        "request_failed:The read operation timed out"
    )


def test_fetch_releases_paginates(monkeypatch) -> None:
    """Release catalog sync should also page through the FRED release list."""
    fetcher = _make_fetcher()

    def fake_api_request(endpoint: str, params: dict[str, str]) -> dict[str, object]:
        assert endpoint == "releases"
        if params["offset"] == "0":
            return {
                "count": 3,
                "limit": 2,
                "offset": 0,
                "releases": [
                    {"id": 10, "name": "Employment Situation", "press_release": True},
                    {"id": 11, "name": "ADP National Employment Report", "press_release": True},
                ],
            }
        return {
            "count": 3,
            "limit": 2,
            "offset": 2,
            "releases": [
                {"id": 12, "name": "Consumer Price Index", "press_release": True}
            ],
        }

    monkeypatch.setattr(fetcher, "_api_request", fake_api_request)

    result = fetcher.fetch_releases()

    assert result["complete"] is True
    assert [row["fred_release_id"] for row in result["releases"]] == [10, 11, 12]


def test_sync_release_dates_deletes_stale_rows_only_on_complete_snapshot(monkeypatch) -> None:
    """A complete, valid snapshot should reconcile stale future dates away."""
    today = date.today()
    fetcher = _make_fetcher()
    session_scope = _make_session_scope()

    monkeypatch.setattr(fred_module, "get_session", session_scope)

    with session_scope() as session:
        employment = Release(fred_release_id=10, name="Employment Situation", press_release=True)
        adp = Release(fred_release_id=11, name="ADP National Employment Report", press_release=True)
        session.add_all([employment, adp])
        session.flush()
        session.add_all(
            [
                ReleaseDate(release_id=employment.id, release_date=today + timedelta(days=7)),
                ReleaseDate(release_id=employment.id, release_date=today + timedelta(days=14)),
                ReleaseDate(release_id=adp.id, release_date=today + timedelta(days=6)),
            ]
        )

    monkeypatch.setattr(
        fetcher,
        "fetch_release_dates",
        lambda *, days_ahead: {
            "release_dates": [
                _release_date_payload(10, "Employment Situation", today + timedelta(days=7)),
                _release_date_payload(
                    11,
                    "ADP National Employment Report",
                    today + timedelta(days=6),
                ),
            ],
            "fetched_count": 2,
            "expected_count": 2,
            "complete": True,
            "degraded_reason": None,
        },
    )

    result = fetcher.sync_release_dates(days_ahead=90)

    assert result["status"] == "complete"
    assert result["removed"] == 1
    assert result["destructive_cleanup_performed"] is True

    with session_scope() as session:
        remaining_dates = session.query(ReleaseDate).order_by(ReleaseDate.release_date).all()

    assert [row.release_date for row in remaining_dates] == [
        today + timedelta(days=6),
        today + timedelta(days=7),
    ]


def test_sync_release_dates_skips_cleanup_when_snapshot_is_incomplete(monkeypatch) -> None:
    """Degraded snapshots may insert rows, but they must not delete existing future dates."""
    today = date.today()
    fetcher = _make_fetcher()
    session_scope = _make_session_scope()

    monkeypatch.setattr(fred_module, "get_session", session_scope)

    with session_scope() as session:
        employment = Release(fred_release_id=10, name="Employment Situation", press_release=True)
        adp = Release(fred_release_id=11, name="ADP National Employment Report", press_release=True)
        session.add_all([employment, adp])
        session.flush()
        session.add_all(
            [
                ReleaseDate(release_id=employment.id, release_date=today + timedelta(days=7)),
                ReleaseDate(release_id=employment.id, release_date=today + timedelta(days=14)),
                ReleaseDate(release_id=adp.id, release_date=today + timedelta(days=6)),
            ]
        )

    monkeypatch.setattr(
        fetcher,
        "fetch_release_dates",
        lambda *, days_ahead: {
            "release_dates": [
                _release_date_payload(10, "Employment Situation", today + timedelta(days=7)),
                _release_date_payload(
                    11,
                    "ADP National Employment Report",
                    today + timedelta(days=6),
                ),
            ],
            "fetched_count": 2,
            "expected_count": 3,
            "complete": False,
            "degraded_reason": "request_failed:page 2 failed",
        },
    )

    result = fetcher.sync_release_dates(days_ahead=90)

    assert result["status"] == "degraded"
    assert result["removed"] == 0
    assert result["destructive_cleanup_performed"] is False

    with session_scope() as session:
        remaining_dates = session.query(ReleaseDate).order_by(ReleaseDate.release_date).all()

    assert [row.release_date for row in remaining_dates] == [
        today + timedelta(days=6),
        today + timedelta(days=7),
        today + timedelta(days=14),
    ]


def test_sync_release_dates_blocks_cleanup_when_anchor_validation_fails(monkeypatch) -> None:
    """Even a complete snapshot should not reconcile destructively if anchor coverage disappears."""
    today = date.today()
    fetcher = _make_fetcher()
    session_scope = _make_session_scope()

    monkeypatch.setattr(fred_module, "get_session", session_scope)

    with session_scope() as session:
        employment = Release(fred_release_id=10, name="Employment Situation", press_release=True)
        adp = Release(fred_release_id=11, name="ADP National Employment Report", press_release=True)
        session.add_all([employment, adp])
        session.flush()
        session.add_all(
            [
                ReleaseDate(release_id=employment.id, release_date=today + timedelta(days=7)),
                ReleaseDate(release_id=adp.id, release_date=today + timedelta(days=6)),
            ]
        )

    monkeypatch.setattr(
        fetcher,
        "fetch_release_dates",
        lambda *, days_ahead: {
            "release_dates": [
                _release_date_payload(
                    11,
                    "ADP National Employment Report",
                    today + timedelta(days=6),
                ),
            ],
            "fetched_count": 1,
            "expected_count": 1,
            "complete": True,
            "degraded_reason": None,
        },
    )

    result = fetcher.sync_release_dates(days_ahead=90)

    assert result["status"] == "degraded"
    assert result["degraded_reason"] == "anchor_validation_failed"
    assert result["destructive_cleanup_performed"] is False
    assert result["anchor_validation"]["missing_releases"] == ["Employment Situation"]

    with session_scope() as session:
        remaining_dates = session.query(ReleaseDate).filter(ReleaseDate.release_date >= today).all()

    assert len(remaining_dates) == 2


def test_sync_release_calendar_returns_degraded_when_lock_not_acquired(monkeypatch) -> None:
    """Concurrent sync attempts should fail fast instead of overlapping reconciliation."""
    fetcher = _make_fetcher()
    captured: dict[str, object] = {}

    @contextmanager
    def fake_lock():
        yield {
            "acquired": False,
            "reason": "local_lock_not_acquired",
        }

    def fake_record(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(fetcher, "_acquire_release_calendar_sync_lock", fake_lock)
    monkeypatch.setattr(fetcher, "_record_release_calendar_sync_run", fake_record)

    result = fetcher.sync_release_calendar(days_ahead=90)

    assert result["status"] == "degraded"
    assert result["ready"] is False
    assert result["degraded_reason"] == "local_lock_not_acquired"
    assert result["dates"]["degraded_reason"] == "local_lock_not_acquired"
    assert captured["lock_acquired"] is False
    assert captured["result"]["status"] == "degraded"


def test_sync_release_calendar_records_audit_for_complete_run(monkeypatch) -> None:
    """Successful syncs should emit an audit record with the combined result payload."""
    fetcher = _make_fetcher()
    captured: dict[str, object] = {}

    @contextmanager
    def fake_lock():
        yield {
            "acquired": True,
            "reason": None,
        }

    def fake_record(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(fetcher, "_acquire_release_calendar_sync_lock", fake_lock)
    monkeypatch.setattr(
        fetcher,
        "sync_releases",
        lambda: {
            "fetched": 2,
            "expected": 2,
            "inserted": 1,
            "updated": 1,
            "complete": True,
            "status": "complete",
            "degraded_reason": None,
        },
    )
    monkeypatch.setattr(
        fetcher,
        "sync_release_dates",
        lambda *, days_ahead: {
            "fetched": 3,
            "expected": 3,
            "inserted": 2,
            "skipped": 1,
            "skipped_missing_release": 0,
            "removed": 0,
            "complete": True,
            "status": "complete",
            "degraded_reason": None,
            "destructive_cleanup_performed": True,
            "integrity_ok": True,
            "anchor_validation": {
                "enabled": True,
                "ok": True,
                "checked_until": date.today().isoformat(),
                "missing_releases": [],
            },
        },
    )
    monkeypatch.setattr(fetcher, "_record_release_calendar_sync_run", fake_record)

    result = fetcher.sync_release_calendar(days_ahead=120)

    assert result["status"] == "complete"
    assert result["ready"] is True
    assert captured["days_ahead"] == 120
    assert captured["lock_acquired"] is True
    assert captured["result"]["dates"]["fetched"] == 3
