"""Query utilities for source-specific economic forecasts."""

from datetime import date, datetime
from decimal import Decimal

from src.db import get_session
from src.db.models import EconomicEventForecast


def _serialize_decimal(value: Decimal | None) -> float | None:
    """Convert database numerics to JSON-safe floats."""
    if value is None:
        return None
    return float(value)


def _serialize_date(value: date | None) -> str | None:
    """Convert dates to ISO strings."""
    if value is None:
        return None
    return value.isoformat()


def _serialize_datetime(value: datetime | None) -> str | None:
    """Convert datetimes to ISO strings."""
    if value is None:
        return None
    return value.isoformat()


class ForecastQuery:
    """Query interface for uploaded economic forecast rows."""

    @staticmethod
    def _apply_filters(
        query,
        *,
        indicator_key: str | None = None,
        source: str | None = None,
        country: str | None = None,
        release_date: date | None = None,
        release_date_from: date | None = None,
        release_date_to: date | None = None,
        source_date_from: date | None = None,
        source_date_to: date | None = None,
        review_status: str | None = None,
        forecast_type: str | None = None,
        economic_event_id: str | None = None,
        parsed_research_id: int | None = None,
        event_name_contains: str | None = None,
    ):
        """Apply common forecast filters to a SQLAlchemy query."""
        if indicator_key:
            query = query.filter(EconomicEventForecast.indicator_key == indicator_key)
        if source:
            query = query.filter(EconomicEventForecast.source == source)
        if country:
            query = query.filter(EconomicEventForecast.country == country)
        if release_date:
            query = query.filter(EconomicEventForecast.release_date == release_date)
        if release_date_from:
            query = query.filter(EconomicEventForecast.release_date >= release_date_from)
        if release_date_to:
            query = query.filter(EconomicEventForecast.release_date <= release_date_to)
        if source_date_from:
            query = query.filter(EconomicEventForecast.source_date >= source_date_from)
        if source_date_to:
            query = query.filter(EconomicEventForecast.source_date <= source_date_to)
        if review_status:
            query = query.filter(EconomicEventForecast.review_status == review_status)
        if forecast_type:
            query = query.filter(EconomicEventForecast.forecast_type == forecast_type)
        if economic_event_id:
            query = query.filter(
                EconomicEventForecast.economic_event_id == economic_event_id
            )
        if parsed_research_id is not None:
            query = query.filter(
                EconomicEventForecast.parsed_research_id == parsed_research_id
            )
        if event_name_contains:
            query = query.filter(
                EconomicEventForecast.event_name.ilike(f"%{event_name_contains}%")
            )
        return query

    @staticmethod
    def _format_forecast_rows(rows: list[EconomicEventForecast]) -> list[dict]:
        """Format ORM rows into API records."""
        return [
            {
                "id": row.id,
                "economic_event_id": row.economic_event_id,
                "parsed_research_id": row.parsed_research_id,
                "source": row.source,
                "source_date": _serialize_date(row.source_date),
                "document_name": row.document_name,
                "document_link": row.document_link,
                "document_hash": row.document_hash,
                "indicator_key": row.indicator_key,
                "event_name": row.event_name,
                "country": row.country,
                "period": row.period,
                "release_date": _serialize_date(row.release_date),
                "forecast_type": row.forecast_type,
                "forecast_value_numeric": _serialize_decimal(
                    row.forecast_value_numeric
                ),
                "forecast_value_low": _serialize_decimal(row.forecast_value_low),
                "forecast_value_high": _serialize_decimal(row.forecast_value_high),
                "forecast_value_text": row.forecast_value_text,
                "forecast_unit": row.forecast_unit,
                "qualifier_text": row.qualifier_text,
                "extraction_confidence": row.extraction_confidence,
                "evidence_text": row.evidence_text,
                "review_status": row.review_status,
                "upload_source": row.upload_source,
                "created_at": _serialize_datetime(row.created_at),
                "updated_at": _serialize_datetime(row.updated_at),
            }
            for row in rows
        ]

    @staticmethod
    def list_forecasts(
        *,
        indicator_key: str | None = None,
        source: str | None = None,
        country: str | None = None,
        release_date: date | None = None,
        release_date_from: date | None = None,
        release_date_to: date | None = None,
        source_date_from: date | None = None,
        source_date_to: date | None = None,
        review_status: str | None = None,
        forecast_type: str | None = None,
        economic_event_id: str | None = None,
        parsed_research_id: int | None = None,
        event_name_contains: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List economic forecast rows with optional filters."""
        with get_session() as session:
            query = session.query(EconomicEventForecast)
            query = ForecastQuery._apply_filters(
                query,
                indicator_key=indicator_key,
                source=source,
                country=country,
                release_date=release_date,
                release_date_from=release_date_from,
                release_date_to=release_date_to,
                source_date_from=source_date_from,
                source_date_to=source_date_to,
                review_status=review_status,
                forecast_type=forecast_type,
                economic_event_id=economic_event_id,
                parsed_research_id=parsed_research_id,
                event_name_contains=event_name_contains,
            )
            rows = (
                query.order_by(
                    EconomicEventForecast.release_date.asc().nullslast(),
                    EconomicEventForecast.source_date.desc().nullslast(),
                    EconomicEventForecast.source.asc(),
                    EconomicEventForecast.created_at.desc(),
                )
                .limit(limit)
                .all()
            )
        return ForecastQuery._format_forecast_rows(rows)
