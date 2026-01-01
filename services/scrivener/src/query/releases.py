"""Query utilities for FRED release calendar data."""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, desc

from src.db import get_session
from src.db.models import Release, ReleaseDate


class ReleaseQuery:
    """Query interface for FRED economic release calendar."""

    @staticmethod
    def get_upcoming(
        days: int = 7,
        press_release_only: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        """Get upcoming releases.

        Args:
            days: Number of days ahead to look
            press_release_only: Only include official press releases
            limit: Max results to return

        Returns:
            List of upcoming releases with dates
        """
        today = date.today()
        end_date = today + timedelta(days=days)

        with get_session() as session:
            query = (
                session.query(Release, ReleaseDate)
                .join(ReleaseDate)
                .filter(
                    and_(
                        ReleaseDate.release_date >= today,
                        ReleaseDate.release_date <= end_date,
                    )
                )
            )

            if press_release_only:
                query = query.filter(Release.press_release == True)

            query = query.order_by(ReleaseDate.release_date, Release.name)

            if limit:
                query = query.limit(limit)

            results = query.all()

            return [
                {
                    "release_date": rd.release_date.isoformat(),
                    "name": release.name,
                    "fred_release_id": release.fred_release_id,
                    "link": release.link,
                    "press_release": release.press_release,
                }
                for release, rd in results
            ]

    @staticmethod
    def get_by_date(target_date: date) -> list[dict]:
        """Get all releases scheduled for a specific date.

        Args:
            target_date: The date to query

        Returns:
            List of releases scheduled for that date
        """
        with get_session() as session:
            results = (
                session.query(Release, ReleaseDate)
                .join(ReleaseDate)
                .filter(ReleaseDate.release_date == target_date)
                .order_by(Release.name)
                .all()
            )

            return [
                {
                    "release_date": rd.release_date.isoformat(),
                    "name": release.name,
                    "fred_release_id": release.fred_release_id,
                    "link": release.link,
                    "press_release": release.press_release,
                }
                for release, rd in results
            ]

    @staticmethod
    def get_today() -> list[dict]:
        """Get releases scheduled for today.

        Returns:
            List of today's releases
        """
        return ReleaseQuery.get_by_date(date.today())

    @staticmethod
    def get_this_week(press_release_only: bool = False) -> list[dict]:
        """Get releases for the current week (Mon-Sun).

        Args:
            press_release_only: Only include official press releases

        Returns:
            List of this week's releases grouped by date
        """
        today = date.today()
        # Find Monday of current week
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)

        with get_session() as session:
            query = (
                session.query(Release, ReleaseDate)
                .join(ReleaseDate)
                .filter(
                    and_(
                        ReleaseDate.release_date >= monday,
                        ReleaseDate.release_date <= sunday,
                    )
                )
            )

            if press_release_only:
                query = query.filter(Release.press_release == True)

            results = query.order_by(ReleaseDate.release_date, Release.name).all()

            return [
                {
                    "release_date": rd.release_date.isoformat(),
                    "day_of_week": rd.release_date.strftime("%A"),
                    "name": release.name,
                    "fred_release_id": release.fred_release_id,
                    "press_release": release.press_release,
                }
                for release, rd in results
            ]

    @staticmethod
    def search(
        query_str: str,
        limit: int = 20,
    ) -> list[dict]:
        """Search releases by name.

        Args:
            query_str: Search term
            limit: Max results

        Returns:
            List of matching releases
        """
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
        """Get a release and its upcoming schedule.

        Args:
            fred_release_id: FRED release ID
            days_ahead: Number of days ahead to include

        Returns:
            Release info with upcoming dates, or None if not found
        """
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
        """Get summary of upcoming releases.

        Args:
            days: Number of days ahead to analyze

        Returns:
            Summary statistics
        """
        today = date.today()
        end_date = today + timedelta(days=days)

        with get_session() as session:
            # Get all upcoming release dates
            results = (
                session.query(Release, ReleaseDate)
                .join(ReleaseDate)
                .filter(
                    and_(
                        ReleaseDate.release_date >= today,
                        ReleaseDate.release_date <= end_date,
                    )
                )
                .all()
            )

            if not results:
                return {
                    "period_days": days,
                    "total_releases": 0,
                    "press_releases": 0,
                    "by_date": {},
                }

            # Count by date
            by_date: dict[str, int] = {}
            press_release_count = 0

            for release, rd in results:
                date_str = rd.release_date.isoformat()
                by_date[date_str] = by_date.get(date_str, 0) + 1
                if release.press_release:
                    press_release_count += 1

            return {
                "period_days": days,
                "total_releases": len(results),
                "press_releases": press_release_count,
                "by_date": by_date,
            }

    @staticmethod
    def get_key_releases_upcoming(days: int = 7) -> list[dict]:
        """Get upcoming key economic releases (press releases only).

        This is a convenience method that filters to official press releases,
        which typically include major indicators like CPI, NFP, GDP, etc.

        Args:
            days: Number of days ahead to look

        Returns:
            List of upcoming key releases
        """
        return ReleaseQuery.get_upcoming(
            days=days,
            press_release_only=True,
        )
