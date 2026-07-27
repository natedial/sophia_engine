"""Query utilities for Fed Board speaker calendar events."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_

from src.config import get_settings
from src.db import get_session
from src.db.models import SpeakerEvent


class SpeakerEventQuery:
    """Query interface for Fed speaker / communications calendar events."""

    @staticmethod
    def _tz() -> ZoneInfo:
        return ZoneInfo(get_settings().timezone)

    @staticmethod
    def _format_event(event: SpeakerEvent) -> dict:
        return {
            "id": event.id,
            "external_id": event.external_id,
            "speaker_id": event.speaker_id,
            "speaker_name": event.speaker_name,
            "title": event.title,
            "event_type": event.event_type,
            "scheduled_start": event.scheduled_start.isoformat()
            if event.scheduled_start
            else None,
            "scheduled_end": event.scheduled_end.isoformat()
            if event.scheduled_end
            else None,
            "location": event.location,
            "description": event.description,
            "url": event.url,
            "source": event.source,
            "status": event.status,
            "speech_id": event.speech_id,
        }

    @staticmethod
    def list_events(
        *,
        days: int = 30,
        speaker: str | None = None,
        event_type: str | None = None,
        status: str | None = "scheduled",
        include_past: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        """List speaker events with optional filters."""
        tz = SpeakerEventQuery._tz()
        now = datetime.now(tz)
        end = now + timedelta(days=days)
        start = now if not include_past else now - timedelta(days=days)

        with get_session() as session:
            query = session.query(SpeakerEvent).filter(
                and_(
                    SpeakerEvent.scheduled_start >= start,
                    SpeakerEvent.scheduled_start <= end,
                )
            )
            if speaker:
                query = query.filter(SpeakerEvent.speaker_name.ilike(f"%{speaker}%"))
            if event_type:
                query = query.filter(SpeakerEvent.event_type == event_type)
            if status:
                query = query.filter(SpeakerEvent.status == status)

            rows = (
                query.order_by(SpeakerEvent.scheduled_start.asc())
                .limit(limit)
                .all()
            )
            return [SpeakerEventQuery._format_event(row) for row in rows]

    @staticmethod
    def get_upcoming(
        *,
        days: int = 14,
        speaker: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get upcoming scheduled speaker events."""
        return SpeakerEventQuery.list_events(
            days=days,
            speaker=speaker,
            event_type=event_type,
            status="scheduled",
            include_past=False,
            limit=limit,
        )

    @staticmethod
    def get_today(
        *,
        speaker: str | None = None,
        event_type: str | None = None,
    ) -> list[dict]:
        """Get today's scheduled speaker events in the configured timezone."""
        tz = SpeakerEventQuery._tz()
        today = datetime.now(tz).date()
        start = datetime.combine(today, time.min, tzinfo=tz)
        end = datetime.combine(today, time.max, tzinfo=tz)

        with get_session() as session:
            query = session.query(SpeakerEvent).filter(
                and_(
                    SpeakerEvent.scheduled_start >= start,
                    SpeakerEvent.scheduled_start <= end,
                    SpeakerEvent.status == "scheduled",
                )
            )
            if speaker:
                query = query.filter(SpeakerEvent.speaker_name.ilike(f"%{speaker}%"))
            if event_type:
                query = query.filter(SpeakerEvent.event_type == event_type)
            rows = query.order_by(SpeakerEvent.scheduled_start.asc()).all()
            return [SpeakerEventQuery._format_event(row) for row in rows]

    @staticmethod
    def get_by_id(event_id: int) -> dict | None:
        """Get a single speaker event by id."""
        with get_session() as session:
            event = (
                session.query(SpeakerEvent)
                .filter(SpeakerEvent.id == event_id)
                .first()
            )
            if not event:
                return None
            return SpeakerEventQuery._format_event(event)

    @staticmethod
    def get_by_speaker(
        speaker_name: str,
        *,
        days: int = 90,
        limit: int = 100,
    ) -> list[dict]:
        """Get upcoming/recent events for a speaker name substring."""
        return SpeakerEventQuery.list_events(
            days=days,
            speaker=speaker_name,
            status=None,
            include_past=True,
            limit=limit,
        )
