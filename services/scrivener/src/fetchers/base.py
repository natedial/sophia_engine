"""Base fetcher class with common functionality."""

import logging
from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.config import get_settings
from src.db import get_session
from src.db.models import FetchLog, Observation, Series, Source

logger = logging.getLogger(__name__)

# Rows per INSERT; keeps bind parameters well under Postgres's limit.
_INSERT_BATCH = 5000


def _as_decimal(value: Any) -> Decimal | None:
    """Compare and store values exactly as their decimal text."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class BaseFetcher(ABC):
    """Abstract base class for all data fetchers."""

    source_name: str = ""
    base_url: str = ""
    rate_limit_per_min: int = 60

    def __init__(self) -> None:
        self.settings = get_settings()
        self._source_id: int | None = None

    @property
    def source_id(self) -> int:
        """Get or create the source ID."""
        if self._source_id is None:
            self._source_id = self._ensure_source()
        return self._source_id

    def _ensure_source(self) -> int:
        """Ensure the source exists in the database."""
        with get_session() as session:
            source = session.query(Source).filter_by(name=self.source_name).first()
            if source is None:
                source = Source(
                    name=self.source_name,
                    base_url=self.base_url,
                    rate_limit_per_min=self.rate_limit_per_min,
                )
                session.add(source)
                session.flush()
            return source.id

    def get_default_start_date(self) -> date:
        """Get the default start date based on lookback setting."""
        years = self.settings.default_lookback_years
        return date.today() - timedelta(days=years * 365)

    @abstractmethod
    def fetch_series_info(self, external_id: str) -> dict[str, Any]:
        """Fetch metadata for a series from the source API.

        Returns dict with keys: name, description, frequency, units, seasonal_adjustment, metadata
        """
        pass

    @abstractmethod
    def fetch_observations(
        self,
        external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch observations for a series.

        Returns list of dicts with keys: date, value, release_date (optional)
        """
        pass

    def ensure_series(
        self,
        external_id: str,
        *,
        info: dict[str, Any] | None = None,
        refresh: bool = False,
    ) -> int:
        """Ensure a series exists in the database, creating if needed."""
        with get_session() as session:
            series = (
                session.query(Series)
                .filter_by(source_id=self.source_id, external_id=external_id)
                .first()
            )
            if info is None:
                info = self.fetch_series_info(external_id)
            if series is None:
                series = Series(
                    source_id=self.source_id,
                    external_id=external_id,
                    name=info.get("name", external_id),
                    description=info.get("description"),
                    frequency=info.get("frequency"),
                    units=info.get("units"),
                    seasonal_adjustment=info.get("seasonal_adjustment"),
                    metadata_=info.get("metadata"),
                )
                session.add(series)
                session.flush()
                logger.info(f"Created series: {external_id} (id={series.id})")
            elif refresh:
                series.name = info.get("name", series.name)
                series.description = info.get("description")
                series.frequency = info.get("frequency")
                series.units = info.get("units")
                series.seasonal_adjustment = info.get("seasonal_adjustment")
                series.metadata_ = info.get("metadata")
            return series.id

    def store_vintages(
        self,
        series_id: int,
        observations: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Store each new vintage of each value; never overwrite.

        Each row has ``date`` and ``value`` and, where the source keeps an
        archive, ``realtime_start`` and ``vintage_source``. A row without
        ``realtime_start`` is recorded as first seen today. A row is written
        only when its value differs from the vintage stored just before it
        for the same date, so a source that repeats an unrevised value under
        a later realtime_start adds nothing.

        Returns counts of new dates, revisions, and unchanged rows.
        """
        counts = {"new_dates": 0, "revisions": 0, "unchanged": 0}
        if not observations:
            return counts

        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        rows = sorted(
            (
                {
                    "date": obs["date"],
                    "value": _as_decimal(obs.get("value")),
                    "realtime_start": obs.get("realtime_start") or today,
                    "vintage_source": obs.get("vintage_source") or "observed",
                }
                for obs in observations
            ),
            key=lambda row: (row["date"], row["realtime_start"]),
        )

        with get_session() as session:
            stored: dict[date, list[tuple[date, Decimal | None]]] = {}
            existing = session.execute(
                select(
                    Observation.date, Observation.realtime_start, Observation.value
                ).where(
                    Observation.series_id == series_id,
                    Observation.date >= rows[0]["date"],
                    Observation.date <= rows[-1]["date"],
                )
            )
            for obs_date, known, value in existing:
                stored.setdefault(obs_date, []).append((known, value))
            for vintages in stored.values():
                vintages.sort(key=lambda item: item[0])

            to_insert = []
            for row in rows:
                vintages = stored.setdefault(row["date"], [])
                if any(known == row["realtime_start"] for known, _ in vintages):
                    counts["unchanged"] += 1
                    continue
                earlier = [item for item in vintages if item[0] < row["realtime_start"]]
                if earlier and earlier[-1][1] == row["value"]:
                    counts["unchanged"] += 1
                    continue
                counts["revisions" if vintages else "new_dates"] += 1
                vintages.append((row["realtime_start"], row["value"]))
                vintages.sort(key=lambda item: item[0])
                to_insert.append({"series_id": series_id, **row})

            for start in range(0, len(to_insert), _INSERT_BATCH):
                stmt = insert(Observation).values(to_insert[start : start + _INSERT_BATCH])
                session.execute(
                    stmt.on_conflict_do_nothing(
                        index_elements=["series_id", "date", "realtime_start"]
                    )
                )

            session.query(Series).filter_by(id=series_id).update(
                {"last_updated": datetime.now(UTC)}
            )

        return counts

    def fetch_and_store(
        self,
        external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        """Fetch data from source and store in database.

        Returns dict with fetch statistics.
        """
        start_date = start_date or self.get_default_start_date()
        end_date = end_date or date.today()

        logger.info(f"Fetching {self.source_name}:{external_id} from {start_date} to {end_date}")

        started_at = datetime.now(UTC)

        try:
            info = self.fetch_series_info(external_id)
            observations = self.fetch_observations(external_id, start_date, end_date)
            series_id = self.ensure_series(
                external_id,
                info=info,
                refresh=True,
            )
            counts = self.store_vintages(series_id, observations)
            records_inserted = counts["new_dates"] + counts["revisions"]

            result = {
                "status": "success",
                "series_id": series_id,
                "external_id": external_id,
                "records_fetched": len(observations),
                "records_inserted": records_inserted,
                "start_date": str(start_date),
                "end_date": str(end_date),
            }
            logger.info(f"Stored {records_inserted} observations for {external_id}")

        except Exception as e:
            logger.error(f"Error fetching {external_id}: {e}")
            result = {
                "status": "error",
                "external_id": external_id,
                "error": str(e),
            }

        completed_at = datetime.now(UTC)

        try:
            self._log_fetch(
                started_at=started_at,
                completed_at=completed_at,
                status=result["status"],
                records_fetched=result.get("records_fetched"),
                records_inserted=result.get("records_inserted"),
                error_message=result.get("error"),
            )
        except Exception as exc:
            logger.warning("Failed to log fetch for %s:%s: %s", self.source_name, external_id, exc)

        return result

    def _log_fetch(
        self,
        started_at: datetime,
        completed_at: datetime,
        status: str,
        records_fetched: int | None = None,
        records_inserted: int | None = None,
        error_message: str | None = None,
        job_id: int | None = None,
    ) -> None:
        """Log a fetch operation."""
        with get_session() as session:
            log = FetchLog(
                job_id=job_id,
                started_at=started_at,
                completed_at=completed_at,
                status=status,
                records_fetched=records_fetched,
                records_inserted=records_inserted,
                error_message=error_message,
            )
            session.add(log)

    def fetch_multiple(
        self,
        external_ids: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch multiple series."""
        results = []
        for external_id in external_ids:
            result = self.fetch_and_store(external_id, start_date, end_date)
            results.append(result)
        return results
