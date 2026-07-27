"""Federal Reserve Board calendar fetcher.

Ingests upcoming communications events from the Board JSON calendar feed.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterator
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import get_settings
from src.db import get_session
from src.db.connection import get_engine
from src.db.models import Speaker, SpeakerEvent, SpeakerEventSyncRun

logger = logging.getLogger(__name__)

CALENDAR_JSON_URL = "https://www.federalreserve.gov/json/calendar.json"
CALENDAR_PAGE_URL = "https://www.federalreserve.gov/newsevents/calendar.htm"
DEFAULT_SOURCE = "Federal Reserve Board"
SPEAKER_CALENDAR_SYNC_LOCK_KEY = 418_034
_speaker_calendar_sync_lock = Lock()
EVENT_UPSERT_CHUNK_SIZE = 200


def _safe_sync_error(exc: Exception) -> str:
    """Describe a sync failure without returning URLs or database details."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{type(exc).__name__}:status={exc.response.status_code}"
    return type(exc).__name__

# Fed feed types we keep for communications calendars.
KEEP_FEED_TYPES = frozenset(
    {
        "Speeches",
        "Testimony",
        "events",
        "FOMC",
        "Conferences",
        "Board",
    }
)

# Statistical / holiday rows stay in FRED or are irrelevant.
SKIP_FEED_TYPES = frozenset({"Stat", "Beige", "Other"})

ROLE_PREFIX_RE = re.compile(
    r"^(?:Chairman|Chair|Vice Chair(?: for Supervision)?|Governor)\s+",
    re.IGNORECASE,
)
TITLE_SPEAKER_RE = re.compile(
    r"^(?P<kind>Speech|Discussion|Testimony)\s*-{1,2}\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>a\.m\.|p\.m\.)$",
    re.IGNORECASE,
)


def unescape_text(value: str | None) -> str | None:
    """Unescape HTML entities and strip whitespace."""
    if value is None:
        return None
    text = html.unescape(value).strip()
    # Collapse simple HTML tags that appear in FOMC descriptions.
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def map_event_type(feed_type: str | None, title: str | None) -> str | None:
    """Map Fed calendar type/title to a normalized event_type, or None to skip."""
    feed = (feed_type or "").strip()
    if feed in SKIP_FEED_TYPES or not feed:
        return None
    if feed not in KEEP_FEED_TYPES:
        return None

    title_l = (title or "").strip().lower()

    if feed == "Testimony":
        return "testimony"
    if feed == "Speeches":
        if "press conference" in title_l:
            return "press_conference"
        if title_l.startswith("discussion"):
            return "discussion"
        return "speech"
    if feed == "events":
        if title_l.startswith("testimony"):
            return "testimony"
        if title_l.startswith("discussion"):
            return "discussion"
        if "press conference" in title_l:
            return "press_conference"
        if title_l.startswith("speech"):
            return "speech"
        return "discussion"
    if feed == "FOMC":
        if "press conference" in title_l:
            return "press_conference"
        return "fomc"
    # Conferences / Board meetings
    return "other"


def extract_speaker_name(title: str | None) -> str | None:
    """Extract a person name from Fed calendar titles when present."""
    if not title:
        return None
    cleaned = unescape_text(title) or ""
    match = TITLE_SPEAKER_RE.match(cleaned)
    if not match:
        return None
    rest = match.group("rest").strip()
    rest = ROLE_PREFIX_RE.sub("", rest).strip(" -–—")
    return rest or None


def parse_event_days(days_value: str | None) -> list[int]:
    """Parse Fed days field into one or more day-of-month integers."""
    if not days_value:
        return []
    parts = re.split(r"[,\s]+", str(days_value).strip())
    days: list[int] = []
    for part in parts:
        if not part:
            continue
        if "-" in part and not part.startswith("-"):
            # Multi-day span like "12-13" — keep the first day for start.
            first = part.split("-", 1)[0].strip()
            if first.isdigit():
                days.append(int(first))
            continue
        if part.isdigit():
            days.append(int(part))
    return days


def parse_time_components(time_value: str | None) -> tuple[int, int]:
    """Parse '10:00 a.m.' style times; default to 00:00 when missing."""
    if not time_value or not str(time_value).strip():
        return 0, 0
    match = TIME_RE.match(str(time_value).strip())
    if not match:
        return 0, 0
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = match.group("ampm").lower()
    if ampm.startswith("p") and hour != 12:
        hour += 12
    if ampm.startswith("a") and hour == 12:
        hour = 0
    return hour, minute


def build_external_id(
    *,
    event_type: str,
    scheduled_start: datetime,
    speaker_name: str | None,
    title: str,
) -> str:
    """Build a stable external id for upserts across syncs."""
    payload = "|".join(
        [
            event_type,
            scheduled_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            (speaker_name or "").strip().lower(),
            title.strip().lower(),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"fedcal:{digest}"


def normalize_calendar_event(
    raw: dict[str, Any],
    *,
    tz: ZoneInfo,
) -> dict[str, Any] | None:
    """Normalize one Fed calendar JSON row into a speaker_events payload."""
    feed_type = raw.get("type")
    title = unescape_text(raw.get("title"))
    if not title:
        return None

    event_type = map_event_type(feed_type if isinstance(feed_type, str) else None, title)
    if event_type is None:
        return None

    month = (raw.get("month") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        return None

    days = parse_event_days(raw.get("days") if isinstance(raw.get("days"), str) else str(raw.get("days") or ""))
    if not days:
        return None

    # Weekly-style multi-day lists belong to statistical releases; communications
    # events are almost always a single day. Keep the first listed day.
    day = days[0]
    hour, minute = parse_time_components(
        raw.get("time") if isinstance(raw.get("time"), str) else None
    )
    year_s, month_s = month.split("-", 1)
    try:
        local_start = datetime(
            int(year_s),
            int(month_s),
            day,
            hour,
            minute,
            tzinfo=tz,
        )
    except ValueError:
        return None

    speaker_name = extract_speaker_name(title)
    description = unescape_text(raw.get("description") if isinstance(raw.get("description"), str) else None)
    location = unescape_text(raw.get("location") if isinstance(raw.get("location"), str) else None)
    url = None
    for key in ("link", "live"):
        candidate = raw.get(key)
        if isinstance(candidate, str) and candidate.strip():
            parsed_url = urlparse(candidate.strip())
            if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
                url = candidate.strip()
                break

    return {
        "external_id": build_external_id(
            event_type=event_type,
            scheduled_start=local_start,
            speaker_name=speaker_name,
            title=title,
        ),
        "speaker_name": speaker_name,
        "title": title,
        "event_type": event_type,
        "scheduled_start": local_start,
        "scheduled_end": None,
        "location": location,
        "description": description,
        "url": url,
        "source": DEFAULT_SOURCE,
        "status": "scheduled",
        "raw_payload": raw,
    }


class FedCalendarFetcher:
    """Fetcher for Federal Reserve Board speaker / communications calendar."""

    def __init__(self, client: httpx.Client | None = None):
        self.settings = get_settings()
        self.tz = ZoneInfo(self.settings.timezone)
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; Scrivener/1.0; "
                    "+https://github.com/scrivener)"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": CALENDAR_PAGE_URL,
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> FedCalendarFetcher:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_calendar_events(self) -> list[dict[str, Any]]:
        """Fetch raw events list from the Board calendar JSON feed."""
        import json

        response = self.client.get(CALENDAR_JSON_URL)
        response.raise_for_status()
        data = json.loads(response.content.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Unexpected calendar JSON shape: expected object")
        events = data.get("events")
        if not isinstance(events, list):
            raise ValueError("Unexpected calendar JSON shape: missing events list")
        return [e for e in events if isinstance(e, dict)]

    def normalize_events(
        self, raw_events: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Normalize and filter raw events. Returns (kept, skipped_count)."""
        kept: list[dict[str, Any]] = []
        skipped = 0
        seen_ids: set[str] = set()
        for raw in raw_events:
            normalized = normalize_calendar_event(raw, tz=self.tz)
            if normalized is None:
                skipped += 1
                continue
            external_id = normalized["external_id"]
            if external_id in seen_ids:
                skipped += 1
                continue
            seen_ids.add(external_id)
            kept.append(normalized)
        return kept, skipped

    @contextmanager
    def _acquire_sync_lock(self) -> Iterator[dict[str, Any]]:
        """Acquire a non-blocking single-flight lock for speaker calendar sync."""
        local_lock_acquired = _speaker_calendar_sync_lock.acquire(blocking=False)
        if not local_lock_acquired:
            yield {"acquired": False, "reason": "local_lock_not_acquired"}
            return

        connection = None
        advisory_lock_acquired = False
        try:
            engine = get_engine()
            if engine.dialect.name == "postgresql":
                connection = engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                advisory_lock_acquired = bool(
                    connection.execute(
                        text("SELECT pg_try_advisory_lock(:lock_key)"),
                        {"lock_key": SPEAKER_CALENDAR_SYNC_LOCK_KEY},
                    ).scalar()
                )
                if not advisory_lock_acquired:
                    yield {
                        "acquired": False,
                        "reason": "postgres_advisory_lock_not_acquired",
                    }
                    return

            yield {"acquired": True, "reason": None}
        finally:
            try:
                if connection is not None and advisory_lock_acquired:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": SPEAKER_CALENDAR_SYNC_LOCK_KEY},
                    )
            finally:
                if connection is not None:
                    connection.close()
                if local_lock_acquired:
                    _speaker_calendar_sync_lock.release()

    def _ensure_speakers(
        self, session: Any, names: set[str]
    ) -> dict[str, int]:
        """Upsert speakers and return name -> id mapping."""
        if not names:
            return {}

        dialect = session.bind.dialect.name if session.bind is not None else ""
        rows = [
            {
                "name": name,
                "title": None,
                "institution": "Federal Reserve",
                "is_active": True,
            }
            for name in sorted(names)
        ]

        if dialect == "postgresql":
            stmt = pg_insert(Speaker).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=[Speaker.name])
            session.execute(stmt)
            session.flush()
        else:
            existing_names = {
                name
                for (name,) in session.query(Speaker.name)
                .filter(Speaker.name.in_(list(names)))
                .all()
            }
            for row in rows:
                if row["name"] not in existing_names:
                    session.add(Speaker(**row))
            session.flush()

        mapping = {
            speaker.name: speaker.id
            for speaker in session.query(Speaker)
            .filter(Speaker.name.in_(list(names)))
            .all()
        }
        return mapping

    def _record_sync_run(self, **fields: Any) -> None:
        with get_session() as session:
            session.add(SpeakerEventSyncRun(**fields))
            session.commit()

    def sync_speaker_calendar(self) -> dict[str, Any]:
        """Fetch, upsert, and reconcile Fed Board speaker calendar events."""
        started_at = datetime.now(timezone.utc)
        inserted = 0
        updated = 0
        cancelled = 0
        events_fetched = 0
        events_kept = 0
        events_skipped = 0

        try:
            with self._acquire_sync_lock() as lock_state:
                if not lock_state["acquired"]:
                    reason = lock_state.get("reason") or "lock_not_acquired"
                    logger.warning(
                        "Skipping speaker calendar sync; lock not acquired: %s",
                        reason,
                    )
                    result = {
                        "status": "skipped",
                        "ready": True,
                        "events_fetched": 0,
                        "events_kept": 0,
                        "events_inserted": 0,
                        "events_updated": 0,
                        "events_cancelled": 0,
                        "events_skipped": 0,
                        "error_message": reason,
                    }
                    try:
                        self._record_sync_run(
                            started_at=started_at,
                            completed_at=datetime.now(timezone.utc),
                            status=result["status"],
                            ready=result["ready"],
                            events_fetched=0,
                            events_kept=0,
                            events_inserted=0,
                            events_updated=0,
                            events_cancelled=0,
                            events_skipped=0,
                            error_message=reason,
                        )
                    except Exception as audit_exc:
                        logger.warning(
                            "Failed to record speaker calendar sync audit: %s",
                            type(audit_exc).__name__,
                        )
                    return result

                raw_events = self.fetch_calendar_events()
                events_fetched = len(raw_events)
                kept, events_skipped = self.normalize_events(raw_events)
                events_kept = len(kept)
                seen_external_ids = {event["external_id"] for event in kept}
                now = datetime.now(timezone.utc)
                speaker_names = {
                    event["speaker_name"]
                    for event in kept
                    if event.get("speaker_name")
                }

                with get_session() as session:
                    # Avoid Supabase's default low statement_timeout on bulk sync.
                    if session.bind is not None and session.bind.dialect.name == "postgresql":
                        session.execute(text("SET LOCAL statement_timeout = '120s'"))

                    speaker_ids = self._ensure_speakers(session, speaker_names)
                    session.commit()

                    # Fresh timeout budget after the speaker commit.
                    if session.bind is not None and session.bind.dialect.name == "postgresql":
                        session.execute(text("SET LOCAL statement_timeout = '120s'"))

                    external_ids = [event["external_id"] for event in kept]
                    existing_by_id: dict[str, SpeakerEvent] = {}
                    for offset in range(0, len(external_ids), EVENT_UPSERT_CHUNK_SIZE):
                        chunk = external_ids[offset : offset + EVENT_UPSERT_CHUNK_SIZE]
                        if not chunk:
                            continue
                        for row in (
                            session.query(SpeakerEvent)
                            .filter(SpeakerEvent.external_id.in_(chunk))
                            .all()
                        ):
                            existing_by_id[row.external_id] = row

                    for event in kept:
                        speaker_name = event["speaker_name"]
                        speaker_id = (
                            speaker_ids.get(speaker_name) if speaker_name else None
                        )
                        existing = existing_by_id.get(event["external_id"])
                        if existing:
                            existing.speaker_id = speaker_id
                            existing.speaker_name = speaker_name
                            existing.title = event["title"]
                            existing.event_type = event["event_type"]
                            existing.scheduled_start = event["scheduled_start"]
                            existing.scheduled_end = event["scheduled_end"]
                            existing.location = event["location"]
                            existing.description = event["description"]
                            existing.url = event["url"]
                            existing.source = event["source"]
                            if existing.status == "cancelled":
                                existing.status = "scheduled"
                            existing.raw_payload = event["raw_payload"]
                            existing.last_seen_at = now
                            existing.updated_at = now
                            updated += 1
                        else:
                            session.add(
                                SpeakerEvent(
                                    external_id=event["external_id"],
                                    speaker_id=speaker_id,
                                    speaker_name=speaker_name,
                                    title=event["title"],
                                    event_type=event["event_type"],
                                    scheduled_start=event["scheduled_start"],
                                    scheduled_end=event["scheduled_end"],
                                    location=event["location"],
                                    description=event["description"],
                                    url=event["url"],
                                    source=event["source"],
                                    status="scheduled",
                                    raw_payload=event["raw_payload"],
                                    first_seen_at=now,
                                    last_seen_at=now,
                                )
                            )
                            inserted += 1

                    future_events = (
                        session.query(SpeakerEvent)
                        .filter(
                            SpeakerEvent.source == DEFAULT_SOURCE,
                            SpeakerEvent.status == "scheduled",
                            SpeakerEvent.scheduled_start >= now,
                        )
                        .all()
                    )
                    for row in future_events:
                        if row.external_id not in seen_external_ids:
                            row.status = "cancelled"
                            row.updated_at = now
                            cancelled += 1

                    session.commit()

            completed_at = datetime.now(timezone.utc)
            result = {
                "status": "complete",
                "ready": True,
                "events_fetched": events_fetched,
                "events_kept": events_kept,
                "events_inserted": inserted,
                "events_updated": updated,
                "events_cancelled": cancelled,
                "events_skipped": events_skipped,
                "error_message": None,
            }
            try:
                self._record_sync_run(
                    started_at=started_at,
                    completed_at=completed_at,
                    status=result["status"],
                    ready=result["ready"],
                    events_fetched=events_fetched,
                    events_kept=events_kept,
                    events_inserted=inserted,
                    events_updated=updated,
                    events_cancelled=cancelled,
                    events_skipped=events_skipped,
                    error_message=None,
                )
            except Exception as audit_exc:
                logger.warning(
                    "Failed to record speaker calendar sync audit: %s",
                    type(audit_exc).__name__,
                )
            logger.info(
                "Speaker calendar sync complete: fetched=%s kept=%s inserted=%s "
                "updated=%s cancelled=%s skipped=%s",
                events_fetched,
                events_kept,
                inserted,
                updated,
                cancelled,
                events_skipped,
            )
            return result
        except Exception as exc:
            safe_error = _safe_sync_error(exc)
            logger.exception("Speaker calendar sync failed: %s", safe_error)
            completed_at = datetime.now(timezone.utc)
            result = {
                "status": "error",
                "ready": False,
                "events_fetched": events_fetched,
                "events_kept": events_kept,
                "events_inserted": inserted,
                "events_updated": updated,
                "events_cancelled": cancelled,
                "events_skipped": events_skipped,
                "error_message": safe_error,
            }
            try:
                self._record_sync_run(
                    started_at=started_at,
                    completed_at=completed_at,
                    status=result["status"],
                    ready=result["ready"],
                    events_fetched=events_fetched,
                    events_kept=events_kept,
                    events_inserted=inserted,
                    events_updated=updated,
                    events_cancelled=cancelled,
                    events_skipped=events_skipped,
                    error_message=safe_error,
                )
            except Exception as audit_exc:
                logger.warning(
                    "Failed to record speaker calendar sync audit: %s",
                    type(audit_exc).__name__,
                )
            return result
