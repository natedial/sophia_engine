"""Economic release calendar management - reads from release_dates table."""

import logging
import re
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from sqlalchemy import and_

from src.config import get_settings
from src.db import get_session
from src.db.models import Release, ReleaseDate

logger = logging.getLogger(__name__)


RELEASE_NAME_PATTERNS = {
    r"(?i)Consumer Price Index|^CPI\\b": "CPI",
    r"(?i)Producer Price Index|^PPI\\b": "PPI",
    r"(?i)Employment Situation|Nonfarm Payrolls|Non-Farm|NFP": "NFP",
    r"(?i)Job Openings|JOLTS": "JOLTS",
    r"(?i)Initial Jobless Claims|Unemployment Insurance Weekly Claims|Jobless Claims": "CLAIMS",
    r"(?i)Gross Domestic Product|^GDP\\b": "GDP",
    r"(?i)Personal Consumption Expenditures|PCE": "PCE",
    r"(?i)FOMC|Federal Open Market Committee|Interest Rate Decision|Federal Funds": "FOMC",
}


class ReleaseCalendar:
    """Reads upcoming releases from release_dates and maps to series."""

    def __init__(self):
        self.settings = get_settings()
        self.tz = ZoneInfo(self.settings.timezone)
        self._compiled_patterns = {
            re.compile(pattern): release_key
            for pattern, release_key in RELEASE_NAME_PATTERNS.items()
        }

    def _match_release_to_definition(self, release_name: str) -> dict | None:
        """Match a release name to series definitions."""
        for pattern, release_key in self._compiled_patterns.items():
            if pattern.search(release_name):
                return RELEASE_DEFINITIONS.get(release_key)
        return None

    def _parse_release_datetime(self, release_date: date, typical_time: str) -> datetime | None:
        """Build a timezone-aware datetime from release_date and typical_time."""
        if not release_date or not typical_time:
            return None

        try:
            hour, minute = typical_time.split(":")
            return datetime(
                release_date.year,
                release_date.month,
                release_date.day,
                int(hour),
                int(minute),
                tzinfo=self.tz,
            )
        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse datetime for release date {release_date}: {e}")
            return None

    def get_upcoming_releases(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict]:
        """Get upcoming releases with mapped series.

        Args:
            start: Start of range (default: now)
            end: End of range (default: 24 hours from now)

        Returns:
            List of releases with mapped series
        """
        now = datetime.now(self.tz)
        start = start or now
        end = end or (start + timedelta(hours=24))

        # Convert to dates for query
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        with get_session() as session:
            query = (
                session.query(Release, ReleaseDate)
                .join(ReleaseDate)
                .filter(
                and_(
                    ReleaseDate.release_date >= start_date,
                    ReleaseDate.release_date <= end_date,
                )
                )
            )

            releases = query.order_by(ReleaseDate.release_date, Release.name).all()

            results = []
            for release, release_date in releases:
                series_config = self._match_release_to_definition(release.name)
                if not series_config:
                    continue

                release_dt = self._parse_release_datetime(
                    release_date.release_date,
                    series_config["typical_time"],
                )
                if not release_dt:
                    continue

                if not (start <= release_dt <= end):
                    continue

                results.append({
                    "id": release_date.id,
                    "release_id": release.fred_release_id,
                    "release_name": release.name,
                    "release_type": series_config.get("release_type", ""),
                    "scheduled_time": release_dt,
                    "bls_series": series_config["bls_series"],
                    "fred_series": series_config["fred_series"],
                })

            return results

    def get_releases_for_today(self) -> list[dict]:
        """Get all mapped releases for today."""
        now = datetime.now(self.tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.get_upcoming_releases(start=start, end=end)

    def get_next_release(self) -> dict | None:
        """Get the next upcoming mapped release."""
        releases = self.get_upcoming_releases()
        return releases[0] if releases else None


# Keep the old release definitions for reference/manual triggers
RELEASE_DEFINITIONS = {
    "CPI": {
        "source": "BLS",
        "bls_series": ["CUSR0000SA0", "CUSR0000SA0L1E", "CUUR0000SA0"],
        "fred_series": ["CPIAUCSL", "CPILFESL"],
        "release_type": "CPI",
        "typical_time": "08:30",
        "frequency": "monthly",
        "description": "Consumer Price Index",
    },
    "PPI": {
        "source": "BLS",
        "bls_series": ["WPSFD4", "WPSFD49104"],
        "fred_series": [],
        "release_type": "PPI",
        "typical_time": "08:30",
        "frequency": "monthly",
        "description": "Producer Price Index",
    },
    "NFP": {
        "source": "BLS",
        "bls_series": ["CES0000000001", "LNS14000000", "CES0500000003", "CES0500000011"],
        "fred_series": ["PAYEMS", "UNRATE"],
        "release_type": "NFP",
        "typical_time": "08:30",
        "frequency": "monthly",
        "description": "Employment Situation (Nonfarm Payrolls)",
    },
    "JOLTS": {
        "source": "BLS",
        "bls_series": ["JTS000000000000000JOL", "JTS000000000000000HIL", "JTS000000000000000QUL"],
        "fred_series": ["JTSJOL"],
        "release_type": "JOLTS",
        "typical_time": "10:00",
        "frequency": "monthly",
        "description": "Job Openings and Labor Turnover Survey",
    },
    "CLAIMS": {
        "source": "FRED",
        "bls_series": [],
        "fred_series": ["ICSA", "CCSA"],
        "release_type": "CLAIMS",
        "typical_time": "08:30",
        "frequency": "weekly",
        "description": "Unemployment Insurance Weekly Claims",
    },
    "GDP": {
        "source": "FRED",
        "bls_series": [],
        "fred_series": ["GDP", "GDPC1", "A191RL1Q225SBEA"],
        "release_type": "GDP",
        "typical_time": "08:30",
        "frequency": "quarterly",
        "description": "Gross Domestic Product",
    },
    "PCE": {
        "source": "FRED",
        "bls_series": [],
        "fred_series": ["PCEPI", "PCEPILFE"],
        "release_type": "PCE",
        "typical_time": "08:30",
        "frequency": "monthly",
        "description": "Personal Consumption Expenditures",
    },
    "FOMC": {
        "source": "FRED",
        "bls_series": [],
        "fred_series": ["FEDFUNDS", "DFEDTARU", "DFEDTARL"],
        "release_type": "FOMC",
        "typical_time": "14:00",
        "frequency": "scheduled",
        "description": "FOMC Interest Rate Decision",
    },
}


def get_release_definitions() -> dict:
    """Get all release definitions."""
    return RELEASE_DEFINITIONS.copy()

