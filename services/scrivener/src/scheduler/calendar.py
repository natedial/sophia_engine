"""Economic release calendar management - reads from economic_events table."""

import logging
import re
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_

from src.config import get_settings
from src.db import get_session
from src.db.models import EconomicEvent

logger = logging.getLogger(__name__)


# Map event_name patterns to series definitions
# Keys are regex patterns to match against event_name
EVENT_SERIES_MAP = {
    # CPI
    r"(?i)^CPI\b|Consumer Price Index": {
        "release_type": "CPI",
        "bls_series": ["CUSR0000SA0", "CUSR0000SA0L1E", "CUUR0000SA0"],
        "fred_series": ["CPIAUCSL", "CPILFESL"],
    },
    # Core CPI specifically
    r"(?i)Core CPI|CPI.*ex.*Food": {
        "release_type": "CPI_CORE",
        "bls_series": ["CUSR0000SA0L1E"],
        "fred_series": ["CPILFESL"],
    },
    # PPI
    r"(?i)^PPI\b|Producer Price Index": {
        "release_type": "PPI",
        "bls_series": ["WPSFD4", "WPSFD49104"],
        "fred_series": [],
    },
    # Employment / NFP
    r"(?i)Nonfarm Payrolls|Non-Farm|NFP|Employment Change": {
        "release_type": "NFP",
        "bls_series": ["CES0000000001", "LNS14000000", "CES0500000003", "CES0500000011"],
        "fred_series": ["PAYEMS", "UNRATE"],
    },
    # Unemployment Rate
    r"(?i)^Unemployment Rate": {
        "release_type": "UNEMPLOYMENT",
        "bls_series": ["LNS14000000"],
        "fred_series": ["UNRATE"],
    },
    # JOLTS
    r"(?i)JOLTS|Job Openings": {
        "release_type": "JOLTS",
        "bls_series": ["JTS000000000000000JOL", "JTS000000000000000HIL", "JTS000000000000000QUL"],
        "fred_series": ["JTSJOL"],
    },
    # Initial Jobless Claims
    r"(?i)Initial.*Claims|Jobless Claims|Initial Claims": {
        "release_type": "CLAIMS",
        "bls_series": [],
        "fred_series": ["ICSA", "CCSA"],
    },
    # Continuing Claims
    r"(?i)Continu.*Claims": {
        "release_type": "CLAIMS_CONTINUING",
        "bls_series": [],
        "fred_series": ["CCSA"],
    },
    # GDP
    r"(?i)^GDP\b|Gross Domestic Product": {
        "release_type": "GDP",
        "bls_series": [],
        "fred_series": ["GDP", "GDPC1", "A191RL1Q225SBEA"],
    },
    # PCE
    r"(?i)PCE|Personal Consumption|Core PCE": {
        "release_type": "PCE",
        "bls_series": [],
        "fred_series": ["PCEPI", "PCEPILFE"],
    },
    # FOMC / Fed
    r"(?i)FOMC|Fed.*Rate|Interest Rate Decision|Federal Funds": {
        "release_type": "FOMC",
        "bls_series": [],
        "fred_series": ["FEDFUNDS", "DFEDTARU", "DFEDTARL"],
    },
    # Retail Sales
    r"(?i)Retail Sales": {
        "release_type": "RETAIL_SALES",
        "bls_series": [],
        "fred_series": ["RSAFS", "RSXFS"],
    },
    # Industrial Production
    r"(?i)Industrial Production": {
        "release_type": "INDUSTRIAL_PROD",
        "bls_series": [],
        "fred_series": ["INDPRO"],
    },
    # ISM Manufacturing
    r"(?i)ISM Manufacturing|ISM Manuf": {
        "release_type": "ISM_MFG",
        "bls_series": [],
        "fred_series": ["MANEMP"],
    },
    # Housing
    r"(?i)Housing Starts|Building Permits": {
        "release_type": "HOUSING",
        "bls_series": [],
        "fred_series": ["HOUST", "PERMIT"],
    },
    # Durable Goods
    r"(?i)Durable Goods": {
        "release_type": "DURABLE_GOODS",
        "bls_series": [],
        "fred_series": ["DGORDER"],
    },
}


class EconomicEventsCalendar:
    """Reads upcoming events from economic_events table and maps to series."""

    def __init__(self):
        self.settings = get_settings()
        self.tz = ZoneInfo(self.settings.timezone)
        self._compiled_patterns = {
            re.compile(pattern): config
            for pattern, config in EVENT_SERIES_MAP.items()
        }

    def _match_event_to_series(self, event_name: str) -> dict | None:
        """Match an event name to series definitions."""
        for pattern, config in self._compiled_patterns.items():
            if pattern.search(event_name):
                return config
        return None

    def _parse_event_datetime(self, event: EconomicEvent) -> datetime | None:
        """Parse event_date and time_ny into a timezone-aware datetime."""
        if not event.event_date:
            return None

        try:
            # time_ny format might be "08:30" or "8:30 AM" etc.
            time_str = event.time_ny.strip()

            # Handle various time formats
            hour, minute = 0, 0
            if ":" in time_str:
                parts = time_str.replace(" AM", "").replace(" PM", "").replace("AM", "").replace("PM", "").split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0

                # Handle PM
                if "PM" in time_str.upper() and hour < 12:
                    hour += 12
                elif "AM" in time_str.upper() and hour == 12:
                    hour = 0

            return datetime(
                event.event_date.year,
                event.event_date.month,
                event.event_date.day,
                hour,
                minute,
                tzinfo=self.tz,
            )
        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse datetime for event {event.event_name}: {e}")
            return None

    def get_upcoming_events(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        country: str = "US",
        importance: list[str] | None = None,
    ) -> list[dict]:
        """Get upcoming economic events that we can map to series.

        Args:
            start: Start of range (default: now)
            end: End of range (default: 24 hours from now)
            country: Country filter (default: US)
            importance: Filter by importance_indicator (e.g., ["High", "Medium"])

        Returns:
            List of events with mapped series
        """
        now = datetime.now(self.tz)
        start = start or now
        end = end or (start + timedelta(hours=24))

        # Convert to dates for query
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        with get_session() as session:
            query = session.query(EconomicEvent).filter(
                and_(
                    EconomicEvent.event_date >= start_date,
                    EconomicEvent.event_date <= end_date,
                    EconomicEvent.country.ilike(f"%{country}%"),
                )
            )

            if importance:
                query = query.filter(EconomicEvent.importance_indicator.in_(importance))

            events = query.order_by(EconomicEvent.event_date, EconomicEvent.time_ny).all()

            results = []
            for event in events:
                series_config = self._match_event_to_series(event.event_name)
                if not series_config:
                    continue  # Skip events we don't have series mappings for

                event_dt = self._parse_event_datetime(event)
                if not event_dt:
                    continue

                # Only include if within time window
                if not (start <= event_dt <= end):
                    continue

                results.append({
                    "id": event.id,
                    "event_name": event.event_name,
                    "release_type": series_config["release_type"],
                    "scheduled_time": event_dt,
                    "period": event.period,
                    "importance": event.importance_indicator,
                    "bls_series": series_config["bls_series"],
                    "fred_series": series_config["fred_series"],
                    "has_result": event.actual_result is not None,
                })

            return results

    def get_events_for_today(self, country: str = "US") -> list[dict]:
        """Get all mapped events for today."""
        now = datetime.now(self.tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return self.get_upcoming_events(start=start, end=end, country=country)

    def get_next_event(self, country: str = "US") -> dict | None:
        """Get the next upcoming mapped event."""
        events = self.get_upcoming_events(country=country)
        return events[0] if events else None


# Keep the old release definitions for reference/manual triggers
RELEASE_DEFINITIONS = {
    "CPI": {
        "source": "BLS",
        "bls_series": ["CUSR0000SA0", "CUSR0000SA0L1E", "CUUR0000SA0"],
        "fred_series": ["CPIAUCSL", "CPILFESL"],
        "typical_time": "08:30",
        "frequency": "monthly",
        "description": "Consumer Price Index",
    },
    "PPI": {
        "source": "BLS",
        "bls_series": ["WPSFD4", "WPSFD49104"],
        "fred_series": [],
        "typical_time": "08:30",
        "frequency": "monthly",
        "description": "Producer Price Index",
    },
    "NFP": {
        "source": "BLS",
        "bls_series": ["CES0000000001", "LNS14000000", "CES0500000003", "CES0500000011"],
        "fred_series": ["PAYEMS", "UNRATE"],
        "typical_time": "08:30",
        "frequency": "monthly",
        "description": "Employment Situation (Nonfarm Payrolls)",
    },
    "JOLTS": {
        "source": "BLS",
        "bls_series": ["JTS000000000000000JOL", "JTS000000000000000HIL", "JTS000000000000000QUL"],
        "fred_series": ["JTSJOL"],
        "typical_time": "10:00",
        "frequency": "monthly",
        "description": "Job Openings and Labor Turnover Survey",
    },
    "CLAIMS": {
        "source": "FRED",
        "bls_series": [],
        "fred_series": ["ICSA", "CCSA"],
        "typical_time": "08:30",
        "frequency": "weekly",
        "description": "Unemployment Insurance Weekly Claims",
    },
    "GDP": {
        "source": "FRED",
        "bls_series": [],
        "fred_series": ["GDP", "GDPC1", "A191RL1Q225SBEA"],
        "typical_time": "08:30",
        "frequency": "quarterly",
        "description": "Gross Domestic Product",
    },
    "PCE": {
        "source": "FRED",
        "bls_series": [],
        "fred_series": ["PCEPI", "PCEPILFE"],
        "typical_time": "08:30",
        "frequency": "monthly",
        "description": "Personal Consumption Expenditures",
    },
    "FOMC": {
        "source": "FRED",
        "bls_series": [],
        "fred_series": ["FEDFUNDS", "DFEDTARU", "DFEDTARL"],
        "typical_time": "14:00",
        "frequency": "scheduled",
        "description": "FOMC Interest Rate Decision",
    },
}


def get_release_definitions() -> dict:
    """Get all release definitions."""
    return RELEASE_DEFINITIONS.copy()


