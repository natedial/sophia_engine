"""Query utilities for FRED release calendar data."""

import logging
from datetime import date, timedelta

from sqlalchemy import and_

from src.db import get_session
from src.db.models import Release, ReleaseDate

logger = logging.getLogger(__name__)


class ReleaseQuery:
    """Query interface for FRED economic release calendar."""

    @staticmethod
    def _query_release_rows(
        start_date: date,
        end_date: date,
        *,
        press_release_only: bool = False,
        limit: int | None = None,
    ) -> list[tuple[ReleaseDate, Release | None]]:
        """Query release rows within a date range."""
        with get_session() as session:
            query = (
                session.query(ReleaseDate, Release)
                .outerjoin(Release, Release.id == ReleaseDate.release_id)
                .filter(
                    and_(
                        ReleaseDate.release_date >= start_date,
                        ReleaseDate.release_date <= end_date,
                    )
                )
            )

            if press_release_only:
                query = query.filter(Release.press_release.is_(True))

            query = query.order_by(
                ReleaseDate.release_date,
                Release.name.asc().nullslast(),
                ReleaseDate.release_id,
            )
            if limit is not None:
                query = query.limit(limit)
            return query.all()

    @staticmethod
    def _format_release_rows(
        rows: list[tuple[ReleaseDate, Release | None]],
    ) -> list[dict]:
        """Format joined rows into API records."""
        return [
            {
                "release_date": rd.release_date.isoformat(),
                "name": release.name if release else f"Release {rd.release_id}",
                "fred_release_id": (
                    release.fred_release_id if release else rd.release_id
                ),
                "link": release.link if release else None,
                "press_release": release.press_release if release else False,
            }
            for rd, release in rows
        ]

    @staticmethod
    def _auto_sync_release_calendar(days_ahead: int) -> bool:
        """Try to sync release calendar data when local table is empty/stale."""
        from src.config import get_settings

        settings = get_settings()
        if not settings.fred_api_key:
            logger.info("Skipping release auto-sync: FRED_API_KEY is not configured")
            return False

        try:
            from src.fetchers.fred import FredFetcher

            fetcher = FredFetcher()
            fetcher.sync_release_calendar(days_ahead=max(days_ahead, 30))
            return True
        except Exception as exc:
            logger.warning("Release auto-sync failed: %s", exc)
            return False

    @staticmethod
    def get_upcoming(
        days: int = 7,
        press_release_only: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        """Get upcoming releases."""
        today = date.today()
        end_date = today + timedelta(days=days)
        rows = ReleaseQuery._query_release_rows(
            today,
            end_date,
            press_release_only=press_release_only,
            limit=limit,
        )

        # Self-heal empty/stale calendars by syncing once, then re-querying.
        if not rows and ReleaseQuery._auto_sync_release_calendar(days_ahead=max(days, 90)):
            rows = ReleaseQuery._query_release_rows(
                today,
                end_date,
                press_release_only=press_release_only,
                limit=limit,
            )

        return ReleaseQuery._format_release_rows(rows)

    @staticmethod
    def get_by_date(target_date: date) -> list[dict]:
        """Get all releases scheduled for a specific date."""
        rows = ReleaseQuery._query_release_rows(target_date, target_date)

        if not rows and target_date >= date.today():
            days_ahead = (target_date - date.today()).days
            if ReleaseQuery._auto_sync_release_calendar(days_ahead=max(days_ahead, 90)):
                rows = ReleaseQuery._query_release_rows(target_date, target_date)

        return ReleaseQuery._format_release_rows(rows)

    @staticmethod
    def get_today() -> list[dict]:
        """Get releases scheduled for today."""
        return ReleaseQuery.get_by_date(date.today())

    @staticmethod
    def get_this_week(press_release_only: bool = False) -> list[dict]:
        """Get releases for the current week (Mon-Sun)."""
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        rows = ReleaseQuery._query_release_rows(
            monday,
            sunday,
            press_release_only=press_release_only,
        )

        if not rows and sunday >= today:
            days_ahead = (sunday - today).days
            if ReleaseQuery._auto_sync_release_calendar(days_ahead=max(days_ahead, 90)):
                rows = ReleaseQuery._query_release_rows(
                    monday,
                    sunday,
                    press_release_only=press_release_only,
                )

        return [
            {
                "release_date": rd.release_date.isoformat(),
                "day_of_week": rd.release_date.strftime("%A"),
                "name": release.name if release else f"Release {rd.release_id}",
                "fred_release_id": (
                    release.fred_release_id if release else rd.release_id
                ),
                "press_release": release.press_release if release else False,
            }
            for rd, release in rows
        ]

    @staticmethod
    def search(
        query_str: str,
        limit: int = 20,
    ) -> list[dict]:
        """Search releases by name."""
        with get_session() as session:
            results = (
                session.query(Release)
                .filter(Release.name.ilike(f"%{query_str}%"))
                .order_by(Release.name)
                .limit(limit)
                .all()
            )

            return [
                {
                    "id": r.id,
                    "fred_release_id": r.fred_release_id,
                    "name": r.name,
                    "link": r.link,
                    "press_release": r.press_release,
                }
                for r in results
            ]

    @staticmethod
    def get_release_schedule(
        fred_release_id: int,
        days_ahead: int = 90,
    ) -> dict | None:
        """Get a release and its upcoming schedule."""
        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        with get_session() as session:
            release = session.query(Release).filter(
                Release.fred_release_id == fred_release_id
            ).first()

            if not release:
                return None

            dates = (
                session.query(ReleaseDate)
                .filter(
                    and_(
                        ReleaseDate.release_id == release.id,
                        ReleaseDate.release_date >= today,
                        ReleaseDate.release_date <= end_date,
                    )
                )
                .order_by(ReleaseDate.release_date)
                .all()
            )

        if not dates and ReleaseQuery._auto_sync_release_calendar(days_ahead=max(days_ahead, 90)):
            with get_session() as session:
                release = session.query(Release).filter(
                    Release.fred_release_id == fred_release_id
                ).first()
                if not release:
                    return None
                dates = (
                    session.query(ReleaseDate)
                    .filter(
                        and_(
                            ReleaseDate.release_id == release.id,
                            ReleaseDate.release_date >= today,
                            ReleaseDate.release_date <= end_date,
                        )
                    )
                    .order_by(ReleaseDate.release_date)
                    .all()
                )

        return {
            "fred_release_id": release.fred_release_id,
            "name": release.name,
            "link": release.link,
            "notes": release.notes,
            "press_release": release.press_release,
            "upcoming_dates": [d.release_date.isoformat() for d in dates],
            "next_release": dates[0].release_date.isoformat() if dates else None,
        }

    @staticmethod
    def get_summary(days: int = 7) -> dict:
        """Get summary of upcoming releases."""
        today = date.today()
        end_date = today + timedelta(days=days)

        rows = ReleaseQuery._query_release_rows(today, end_date)
        if not rows and ReleaseQuery._auto_sync_release_calendar(days_ahead=max(days, 90)):
            rows = ReleaseQuery._query_release_rows(today, end_date)

        if not rows:
            return {
                "period_days": days,
                "total_releases": 0,
                "press_releases": 0,
                "by_date": {},
            }

        by_date: dict[str, int] = {}
        press_release_count = 0

        for rd, release in rows:
            date_str = rd.release_date.isoformat()
            by_date[date_str] = by_date.get(date_str, 0) + 1
            if release and release.press_release:
                press_release_count += 1

        return {
            "period_days": days,
            "total_releases": len(rows),
            "press_releases": press_release_count,
            "by_date": by_date,
        }

    @staticmethod
    def get_key_releases_upcoming(days: int = 7) -> list[dict]:
        """Get upcoming key economic releases (press releases only)."""
        return ReleaseQuery.get_upcoming(
            days=days,
            press_release_only=True,
        )
