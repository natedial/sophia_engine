"""Tests for Fed Board speaker calendar normalization and sync."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Speaker, SpeakerEvent, SpeakerEventSyncRun
from src.fetchers import fed_calendar as fed_calendar_module
from src.fetchers.fed_calendar import (
    FedCalendarFetcher,
    extract_speaker_name,
    map_event_type,
    normalize_calendar_event,
)


TZ = ZoneInfo("America/New_York")


def _sample_events() -> list[dict]:
    return [
        {
            "description": "Navigating Economic Shocks",
            "live": "https://www.youtube.com/watch?v=example",
            "location": "At Stanford, California",
            "title": "Speech - Vice Chair Philip N. Jefferson",
            "time": "7:00 p.m.",
            "month": "2026-07",
            "days": "16",
            "type": "Speeches",
        },
        {
            "description": "Semiannual Monetary Policy Report to Congress",
            "location": "Before the U.S. House Financial Services Committee",
            "title": "Testimony - Chairman Kevin Warsh",
            "time": "10:00 a.m.",
            "month": "2026-07",
            "days": "14",
            "type": "Testimony",
        },
        {
            "description": "<p>Two-day meeting</p>",
            "title": "FOMC Meeting",
            "time": "2:00 p.m.",
            "month": "2026-07",
            "days": "29",
            "type": "FOMC",
        },
        {
            "title": "Z.1 - Financial Accounts of the United States",
            "time": "12:00 p.m.",
            "month": "2026-07",
            "days": "9",
            "type": "Stat",
        },
        {
            "description": "Conversation with Governor Bowman",
            "location": "Virtual",
            "title": "Discussion -- Governor Michelle W. Bowman",
            "time": "9:15 a.m.",
            "month": "",
            "days": "6",
            "type": "events",
        },
    ]


def _make_fetcher(session_scope) -> FedCalendarFetcher:
    fetcher = FedCalendarFetcher.__new__(FedCalendarFetcher)
    fetcher.settings = SimpleNamespace(timezone="America/New_York")
    fetcher.tz = TZ
    fetcher._owns_client = False
    fetcher.client = SimpleNamespace(close=lambda: None)
    return fetcher


def _make_session_scope():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Speaker.__table__.create(engine)
    SpeakerEvent.__table__.create(engine)
    SpeakerEventSyncRun.__table__.create(engine)
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


def test_map_event_type_keeps_communications_and_skips_stat() -> None:
    assert map_event_type("Speeches", "Speech - Governor Cook") == "speech"
    assert map_event_type("Testimony", "Testimony - Chair Powell") == "testimony"
    assert map_event_type("events", "Discussion -- Governor Bowman") == "discussion"
    assert map_event_type("FOMC", "FOMC Meeting") == "fomc"
    assert map_event_type("FOMC", "FOMC Press Conference") == "press_conference"
    assert map_event_type("Stat", "CPI") is None
    assert map_event_type("Beige", "Beige Book") is None
    assert map_event_type("Other", "Holiday") is None


def test_extract_speaker_name_from_title() -> None:
    assert (
        extract_speaker_name("Speech - Vice Chair Philip N. Jefferson")
        == "Philip N. Jefferson"
    )
    assert (
        extract_speaker_name("Discussion -- Governor Michelle W. Bowman")
        == "Michelle W. Bowman"
    )
    assert extract_speaker_name("FOMC Meeting") is None


def test_normalize_calendar_event_parses_et_time_and_skips_invalid() -> None:
    kept = normalize_calendar_event(_sample_events()[0], tz=TZ)
    assert kept is not None
    assert kept["event_type"] == "speech"
    assert kept["speaker_name"] == "Philip N. Jefferson"
    assert kept["scheduled_start"] == datetime(2026, 7, 16, 19, 0, tzinfo=TZ)
    assert kept["url"] == "https://www.youtube.com/watch?v=example"

    assert normalize_calendar_event(_sample_events()[3], tz=TZ) is None  # Stat
    assert normalize_calendar_event(_sample_events()[4], tz=TZ) is None  # empty month


def test_normalize_events_filters_and_dedupes() -> None:
    fetcher = _make_fetcher(None)
    kept, skipped = fetcher.normalize_events(_sample_events())
    types = {event["event_type"] for event in kept}
    assert types == {"speech", "testimony", "fomc"}
    assert len(kept) == 3
    assert skipped == 2


def test_sync_speaker_calendar_upserts_and_cancels_missing(monkeypatch) -> None:
    session_scope = _make_session_scope()
    monkeypatch.setattr(fed_calendar_module, "get_session", session_scope)

    fetcher = _make_fetcher(session_scope)
    monkeypatch.setattr(fetcher, "fetch_calendar_events", lambda: _sample_events())

    result = fetcher.sync_speaker_calendar()
    assert result["ready"] is True
    assert result["status"] == "complete"
    assert result["events_inserted"] == 3
    assert result["events_skipped"] == 2

    with session_scope() as session:
        rows = session.query(SpeakerEvent).all()
        assert len(rows) == 3
        speakers = session.query(Speaker).all()
        assert {s.name for s in speakers} == {
            "Philip N. Jefferson",
            "Kevin Warsh",
        }

    # Second sync with one future event removed should cancel it.
    reduced = [
        event
        for event in _sample_events()
        if event["type"] in {"Speeches", "FOMC"}
    ]
    monkeypatch.setattr(fetcher, "fetch_calendar_events", lambda: reduced)

    # Force "now" before the testimony so cancellation applies to future rows.
    future_now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return future_now.replace(tzinfo=None)
            return future_now.astimezone(tz)

    monkeypatch.setattr(fed_calendar_module, "datetime", _FrozenDateTime)

    result2 = fetcher.sync_speaker_calendar()
    assert result2["ready"] is True
    assert result2["events_updated"] >= 1
    assert result2["events_cancelled"] == 1

    with session_scope() as session:
        testimony = (
            session.query(SpeakerEvent)
            .filter(SpeakerEvent.event_type == "testimony")
            .one()
        )
        assert testimony.status == "cancelled"
        speech = (
            session.query(SpeakerEvent)
            .filter(SpeakerEvent.event_type == "speech")
            .one()
        )
        assert speech.status == "scheduled"

        audits = session.query(SpeakerEventSyncRun).all()
        assert len(audits) >= 2
        assert audits[-1].ready is True


def test_sync_speaker_calendar_records_error(monkeypatch) -> None:
    session_scope = _make_session_scope()
    monkeypatch.setattr(fed_calendar_module, "get_session", session_scope)

    fetcher = _make_fetcher(session_scope)

    def boom() -> list[dict]:
        raise RuntimeError("network down")

    monkeypatch.setattr(fetcher, "fetch_calendar_events", boom)
    result = fetcher.sync_speaker_calendar()
    assert result["ready"] is False
    assert result["status"] == "error"
    assert "network down" in (result["error_message"] or "")

    with session_scope() as session:
        audit = session.query(SpeakerEventSyncRun).one()
        assert audit.ready is False
        assert audit.status == "error"
