"""Base fetcher class with common functionality."""

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from src.config import get_settings
from src.db import get_session
from src.db.models import FetchLog, Observation, Series, Source

logger = logging.getLogger(__name__)


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

    def ensure_series(self, external_id: str) -> int:
        """Ensure a series exists in the database, creating if needed."""
        with get_session() as session:
            series = (
                session.query(Series)
                .filter_by(source_id=self.source_id, external_id=external_id)
                .first()
            )
            if series is None:
                info = self.fetch_series_info(external_id)
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
            return series.id

    def upsert_observations(
        self,
        series_id: int,
        observations: list[dict[str, Any]],
    ) -> int:
        """Upsert observations into the database.

        Uses PostgreSQL ON CONFLICT to update existing records.
        Returns the number of records upserted.
        """
        if not observations:
            return 0

        with get_session() as session:
            stmt = insert(Observation).values(
                [
                    {
                        "series_id": series_id,
                        "date": obs["date"],
                        "value": obs.get("value"),
                        "release_date": obs.get("release_date"),
                        "revision_num": obs.get("revision_num", 0),
                    }
                    for obs in observations
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["series_id", "date", "revision_num"],
                set_={
                    "value": stmt.excluded.value,
                    "release_date": stmt.excluded.release_date,
                },
            )
            session.execute(stmt)

            # Update series last_updated timestamp
            session.query(Series).filter_by(id=series_id).update(
                {"last_updated": datetime.utcnow()}
            )

        return len(observations)

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

        started_at = datetime.utcnow()

        try:
            series_id = self.ensure_series(external_id)
            observations = self.fetch_observations(external_id, start_date, end_date)
            records_inserted = self.upsert_observations(series_id, observations)

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

        completed_at = datetime.utcnow()

        # Log the fetch operation
        self._log_fetch(
            started_at=started_at,
            completed_at=completed_at,
            status=result["status"],
            records_fetched=result.get("records_fetched"),
            records_inserted=result.get("records_inserted"),
            error_message=result.get("error"),
        )

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
