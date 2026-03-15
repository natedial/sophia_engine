"""Query utilities for time series data."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, desc

from src.db import get_session
from src.db.models import Series, Observation, Source


def _infer_units(
    *,
    external_id: str,
    name: str | None,
    units: str | None,
    source: str | None,
) -> str | None:
    if units and units.strip():
        return units

    series_name = (name or "").lower()
    source_name = (source or "").upper()

    if source_name == "BLS":
        if external_id.startswith("CES"):
            if external_id.endswith("0003") or "average hourly earnings" in series_name:
                return "Dollars per hour"
            if external_id.endswith("0011") or "average weekly earnings" in series_name:
                return "Dollars per week"
            if "average weekly hours" in series_name:
                return "Hours"
            if "payroll" in series_name or external_id.endswith("0001"):
                return "Thousands of persons"
        if external_id.startswith("LNS"):
            if "rate" in series_name or "ratio" in series_name:
                return "Percent"
            if "level" in series_name or "labor force" in series_name or "employment" in series_name:
                return "Thousands of persons"
        if external_id.startswith("JTS"):
            if external_id.endswith("JOR") or external_id.endswith("QUR") or "rate" in series_name:
                return "Percent"
            return "Thousands of jobs"
        if external_id.startswith("CIU"):
            return "Index"
        if external_id.startswith("CU") or external_id.startswith("WP"):
            return "Index"

    if source_name == "FRED":
        if "percent" in series_name or "rate" in series_name:
            return "Percent"
        if "index" in series_name:
            return "Index"

    return None


def _resolve_series_row(
    session,
    *,
    external_id: str,
    source: str | None = None,
) -> Series | None:
    query = session.query(Series).filter(Series.external_id == external_id)
    if source:
        return query.join(Source).filter(Source.name == source.upper()).first()

    rows = (
        query.outerjoin(Source)
        .order_by(func.lower(Source.name).asc().nullslast(), Series.id.asc())
        .all()
    )
    if not rows:
        return None

    source_names = {
        str(row.source.name).upper()
        for row in rows
        if row.source is not None and row.source.name
    }
    if len(source_names) > 1:
        raise ValueError(
            f"series '{external_id}' exists in multiple sources; pass source explicitly"
        )
    return rows[0]


def _series_payload(series: Series) -> dict[str, Any]:
    inferred_units = _infer_units(
        external_id=series.external_id,
        name=series.name,
        units=series.units,
        source=series.source.name if series.source else None,
    )
    return {
        "id": series.id,
        "external_id": series.external_id,
        "name": series.name,
        "description": series.description,
        "frequency": series.frequency,
        "units": inferred_units,
        "source": series.source.name if series.source else None,
        "last_updated": series.last_updated.isoformat() if series.last_updated else None,
    }


class SeriesQuery:
    """Query interface for time series data."""

    @staticmethod
    def get_series_info(external_id: str, source: str | None = None) -> dict | None:
        """Get metadata for a series.

        Args:
            external_id: Series ID (e.g., 'GDP', 'UNRATE')
            source: Optional source filter ('FRED', 'BLS')

        Returns:
            Series metadata dict or None if not found
        """
        with get_session() as session:
            series = _resolve_series_row(
                session,
                external_id=external_id,
                source=source,
            )

            if not series:
                return None

            return _series_payload(series)

    @staticmethod
    def get_latest(external_id: str, source: str | None = None) -> dict | None:
        """Get the most recent observation for a series.

        Args:
            external_id: Series ID
            source: Optional source filter

        Returns:
            Dict with date and value, or None
        """
        with get_session() as session:
            series = _resolve_series_row(
                session,
                external_id=external_id,
                source=source,
            )
            if not series:
                return None

            obs = (
                session.query(Observation)
                .filter(Observation.series_id == series.id)
                .order_by(desc(Observation.date))
                .first()
            )

            if not obs:
                return None

            return {
                "series_id": external_id,
                "date": obs.date.isoformat(),
                "value": float(obs.value) if obs.value is not None else None,
            }

    @staticmethod
    def get_observations(
        external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Get observations for a series within a date range.

        Args:
            external_id: Series ID
            start_date: Start of range (default: 1 year ago)
            end_date: End of range (default: today)
            source: Optional source filter
            limit: Max number of observations to return

        Returns:
            List of observations sorted by date ascending
        """
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=365))

        with get_session() as session:
            series = _resolve_series_row(
                session,
                external_id=external_id,
                source=source,
            )
            if not series:
                return []

            obs_query = (
                session.query(Observation)
                .filter(
                    and_(
                        Observation.series_id == series.id,
                        Observation.date >= start_date,
                        Observation.date <= end_date,
                    )
                )
                .order_by(Observation.date)
            )

            if limit:
                obs_query = obs_query.limit(limit)

            observations = obs_query.all()

            return [
                {
                    "date": obs.date.isoformat(),
                    "value": float(obs.value) if obs.value is not None else None,
                }
                for obs in observations
            ]

    @staticmethod
    def get_multiple_latest(
        external_ids: list[str],
        source: str | None = None,
    ) -> dict[str, dict | None]:
        """Get latest values for multiple series.

        Args:
            external_ids: List of series IDs

        Returns:
            Dict mapping series ID to latest observation
        """
        results = {}
        for external_id in external_ids:
            results[external_id] = SeriesQuery.get_latest(external_id, source=source)
        return results

    @staticmethod
    def search_series(
        query: str,
        source: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search for series by name or description.

        Args:
            query: Search term
            source: Optional source filter
            limit: Max results

        Returns:
            List of matching series
        """
        with get_session() as session:
            search_pattern = f"%{query}%"

            q = session.query(Series).filter(
                Series.name.ilike(search_pattern)
                | Series.external_id.ilike(search_pattern)
                | Series.description.ilike(search_pattern)
            )

            if source:
                q = q.join(Source).filter(Source.name == source.upper())

            results = q.limit(limit).all()

            return [
                {
                    "external_id": s.external_id,
                    "name": s.name,
                    "description": s.description,
                    "source": s.source.name if s.source else None,
                    "frequency": s.frequency,
                    "units": _infer_units(
                        external_id=s.external_id,
                        name=s.name,
                        units=s.units,
                        source=s.source.name if s.source else None,
                    ),
                }
                for s in results
            ]

    @staticmethod
    def list_series(source: str | None = None) -> list[dict]:
        """List all available series.

        Args:
            source: Optional source filter

        Returns:
            List of all series
        """
        with get_session() as session:
            query = session.query(Series)

            if source:
                query = query.join(Source).filter(Source.name == source.upper())

            results = query.order_by(Series.external_id).all()

            return [
                {
                    "external_id": s.external_id,
                    "name": s.name,
                    "source": s.source.name if s.source else None,
                    "frequency": s.frequency,
                    "last_updated": s.last_updated.isoformat() if s.last_updated else None,
                }
                for s in results
            ]

    @staticmethod
    def get_change(
        external_id: str,
        periods: int = 1,
        pct: bool = True,
        source: str | None = None,
    ) -> dict | None:
        """Calculate change from N periods ago.

        Args:
            external_id: Series ID
            periods: Number of periods back to compare
            pct: Return percentage change if True, absolute if False

        Returns:
            Dict with current, previous, and change values
        """
        with get_session() as session:
            series = _resolve_series_row(
                session,
                external_id=external_id,
                source=source,
            )
            if not series:
                return None

            observations = (
                session.query(Observation)
                .filter(Observation.series_id == series.id)
                .order_by(desc(Observation.date))
                .limit(periods + 1)
                .all()
            )

            if len(observations) < periods + 1:
                return None

            current = observations[0]
            previous = observations[periods]

            if current.value is None or previous.value is None:
                return None

            curr_val = float(current.value)
            prev_val = float(previous.value)

            if pct and prev_val != 0:
                change = ((curr_val - prev_val) / prev_val) * 100
                change_type = "percent"
            elif pct:
                change = None
                change_type = "percent_undefined_zero_base"
            else:
                change = curr_val - prev_val
                change_type = "absolute"

            return {
                "series_id": external_id,
                "current_date": current.date.isoformat(),
                "current_value": curr_val,
                "previous_date": previous.date.isoformat(),
                "previous_value": prev_val,
                "change": round(change, 4) if change is not None else None,
                "change_type": change_type,
            }
