"""FRED (Federal Reserve Economic Data) fetcher."""

import logging
from datetime import date, timedelta
from typing import Any

import httpx
from fredapi import Fred

from src.db import get_session
from src.db.models import Release, ReleaseDate
from src.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)


# Key FRED series for initial setup
CORE_SERIES = {
    # GDP & Growth
    "GDP": "Gross Domestic Product",
    "GDPC1": "Real Gross Domestic Product",
    "A191RL1Q225SBEA": "Real GDP Growth Rate",
    # Inflation
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
    "CPILFESL": "Core CPI (Less Food and Energy)",
    "PCEPI": "Personal Consumption Expenditures Price Index",
    "PCEPILFE": "Core PCE Price Index",
    # Employment
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "Total Nonfarm Payrolls",
    "ICSA": "Initial Jobless Claims",
    "CCSA": "Continued Claims",
    "JTSJOL": "Job Openings (JOLTS)",
    # Interest Rates
    "DFF": "Federal Funds Effective Rate (Daily)",
    "FEDFUNDS": "Federal Funds Effective Rate (Monthly)",
    "DFEDTARU": "Federal Funds Target Rate Upper",
    "DFEDTARL": "Federal Funds Target Rate Lower",
    "SOFR": "Secured Overnight Financing Rate",
    # Treasury Yields
    "DGS1MO": "1-Month Treasury",
    "DGS3MO": "3-Month Treasury",
    "DGS6MO": "6-Month Treasury",
    "DGS1": "1-Year Treasury",
    "DGS2": "2-Year Treasury",
    "DGS5": "5-Year Treasury",
    "DGS7": "7-Year Treasury",
    "DGS10": "10-Year Treasury",
    "DGS20": "20-Year Treasury",
    "DGS30": "30-Year Treasury",
    # Spreads
    "T10Y2Y": "10-Year Treasury Minus 2-Year Treasury",
    "T10Y3M": "10-Year Treasury Minus 3-Month Treasury",
    # Other
    "SP500": "S&P 500 Index",
    "DTWEXBGS": "Trade Weighted US Dollar Index",
    "VIXCLS": "CBOE Volatility Index (VIX)",
}


class FredFetcher(BaseFetcher):
    """Fetcher for FRED (Federal Reserve Economic Data)."""

    source_name = "FRED"
    base_url = "https://api.stlouisfed.org/fred"
    rate_limit_per_min = 120

    def __init__(self) -> None:
        super().__init__()
        if not self.settings.fred_api_key:
            raise ValueError("FRED_API_KEY is required. Get one at https://fred.stlouisfed.org/docs/api/api_key.html")
        self._client = Fred(api_key=self.settings.fred_api_key)

    def fetch_series_info(self, external_id: str) -> dict[str, Any]:
        """Fetch series metadata from FRED."""
        info = self._client.get_series_info(external_id)

        # Map FRED frequency codes to human-readable
        freq_map = {
            "D": "daily",
            "W": "weekly",
            "BW": "biweekly",
            "M": "monthly",
            "Q": "quarterly",
            "SA": "semiannual",
            "A": "annual",
        }

        return {
            "name": info.get("title", external_id),
            "description": info.get("notes"),
            "frequency": freq_map.get(info.get("frequency_short"), info.get("frequency")),
            "units": info.get("units"),
            "seasonal_adjustment": info.get("seasonal_adjustment_short"),
            "metadata": {
                "fred_id": info.get("id"),
                "realtime_start": str(info.get("realtime_start")),
                "realtime_end": str(info.get("realtime_end")),
                "observation_start": str(info.get("observation_start")),
                "observation_end": str(info.get("observation_end")),
                "popularity": info.get("popularity"),
            },
        }

    def fetch_observations(
        self,
        external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch observations from FRED."""
        start_date = start_date or self.get_default_start_date()
        end_date = end_date or date.today()

        # fredapi returns a pandas Series
        data = self._client.get_series(
            external_id,
            observation_start=start_date,
            observation_end=end_date,
        )

        observations = []
        for obs_date, value in data.items():
            # Skip NaN values
            if value != value:  # NaN check
                continue
            observations.append({
                "date": obs_date.date() if hasattr(obs_date, "date") else obs_date,
                "value": float(value),
            })

        return observations

    def fetch_with_revisions(
        self,
        external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch observations with revision history (vintage dates).

        This is useful for understanding how data was revised over time.
        """
        start_date = start_date or self.get_default_start_date()
        end_date = end_date or date.today()

        # Get all vintage dates for this series
        vintages = self._client.get_series_all_releases(external_id)

        observations = []
        for _, row in vintages.iterrows():
            if row["value"] != row["value"]:  # NaN check
                continue
            obs_date = row.name
            if hasattr(obs_date, "date"):
                obs_date = obs_date.date()
            if start_date <= obs_date <= end_date:
                observations.append({
                    "date": obs_date,
                    "value": float(row["value"]),
                    "release_date": row.get("realtime_start"),
                })

        return observations

    @classmethod
    def get_core_series(cls) -> dict[str, str]:
        """Get the dictionary of core FRED series."""
        return CORE_SERIES.copy()

    def fetch_core_series(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all core series."""
        return self.fetch_multiple(
            list(CORE_SERIES.keys()),
            start_date=start_date,
            end_date=end_date,
        )

    # -------------------------------------------------------------------------
    # Release Calendar Methods
    # -------------------------------------------------------------------------

    def _api_request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a direct API request to FRED."""
        url = f"{self.base_url}/{endpoint}"
        default_params = {
            "api_key": self.settings.fred_api_key,
            "file_type": "json",
        }
        if params:
            default_params.update(params)

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=default_params)
            response.raise_for_status()
            return response.json()

    def fetch_releases(self) -> list[dict[str, Any]]:
        """Fetch all FRED releases (economic data release categories).

        Returns a list of releases with their metadata.
        """
        data = self._api_request("releases")
        releases = data.get("releases", [])

        return [
            {
                "fred_release_id": r["id"],
                "name": r["name"],
                "link": r.get("link"),
                "notes": r.get("notes"),
                "press_release": r.get("press_release", True),
            }
            for r in releases
        ]

    def fetch_release_dates(
        self,
        release_id: int | None = None,
        days_ahead: int = 30,
        include_past: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch release dates from FRED.

        Args:
            release_id: Specific release ID, or None for all releases
            days_ahead: Number of days ahead to look
            include_past: If True, include past release dates

        Returns:
            List of release date records
        """
        today = date.today()
        params = {
            "include_release_dates_with_no_data": "true",
        }

        if release_id:
            # Fetch dates for specific release
            endpoint = "release/dates"
            params["release_id"] = str(release_id)
        else:
            # Fetch all upcoming release dates
            endpoint = "releases/dates"

        if not include_past:
            params["realtime_start"] = today.isoformat()
            params["realtime_end"] = (today + timedelta(days=days_ahead)).isoformat()

        data = self._api_request(endpoint, params)
        release_dates = data.get("release_dates", [])

        return [
            {
                "fred_release_id": rd["release_id"],
                "release_name": rd.get("release_name", ""),
                "release_date": date.fromisoformat(rd["date"]),
            }
            for rd in release_dates
        ]

    def sync_releases(self) -> dict[str, int]:
        """Sync all FRED releases to the database.

        Returns:
            Dict with counts of inserted/updated releases
        """
        releases = self.fetch_releases()
        inserted = 0
        updated = 0

        with get_session() as session:
            for r in releases:
                existing = session.query(Release).filter_by(
                    fred_release_id=r["fred_release_id"]
                ).first()

                if existing:
                    # Update existing
                    existing.name = r["name"]
                    existing.link = r["link"]
                    existing.notes = r["notes"]
                    existing.press_release = r["press_release"]
                    updated += 1
                else:
                    # Insert new
                    release = Release(
                        fred_release_id=r["fred_release_id"],
                        name=r["name"],
                        link=r["link"],
                        notes=r["notes"],
                        press_release=r["press_release"],
                    )
                    session.add(release)
                    inserted += 1

            session.commit()

        logger.info(f"Synced releases: {inserted} inserted, {updated} updated")
        return {"inserted": inserted, "updated": updated}

    def sync_release_dates(self, days_ahead: int = 90) -> dict[str, int]:
        """Sync upcoming release dates to the database.

        Args:
            days_ahead: Number of days ahead to sync

        Returns:
            Dict with counts of inserted/skipped dates
        """
        release_dates = self.fetch_release_dates(days_ahead=days_ahead)
        inserted = 0
        skipped = 0

        with get_session() as session:
            # Build a map of fred_release_id -> release.id
            releases = {r.fred_release_id: r.id for r in session.query(Release).all()}

            for rd in release_dates:
                fred_id = rd["fred_release_id"]
                if fred_id not in releases:
                    # Release not in our database, skip
                    skipped += 1
                    continue

                release_id = releases[fred_id]
                release_date_val = rd["release_date"]

                # Check if already exists
                existing = session.query(ReleaseDate).filter_by(
                    release_id=release_id,
                    release_date=release_date_val,
                ).first()

                if not existing:
                    date_record = ReleaseDate(
                        release_id=release_id,
                        release_date=release_date_val,
                    )
                    session.add(date_record)
                    inserted += 1
                else:
                    skipped += 1

            session.commit()

        logger.info(f"Synced release dates: {inserted} inserted, {skipped} skipped")
        return {"inserted": inserted, "skipped": skipped}

    def get_upcoming_releases(self, days: int = 7) -> list[dict[str, Any]]:
        """Get upcoming releases from the database.

        Args:
            days: Number of days ahead to look

        Returns:
            List of upcoming releases with dates
        """
        today = date.today()
        end_date = today + timedelta(days=days)

        with get_session() as session:
            results = (
                session.query(Release, ReleaseDate)
                .join(ReleaseDate)
                .filter(
                    ReleaseDate.release_date >= today,
                    ReleaseDate.release_date <= end_date,
                )
                .order_by(ReleaseDate.release_date)
                .all()
            )

            return [
                {
                    "fred_release_id": release.fred_release_id,
                    "name": release.name,
                    "release_date": rd.release_date,
                    "link": release.link,
                    "press_release": release.press_release,
                }
                for release, rd in results
            ]

    def sync_release_calendar(self, days_ahead: int = 90) -> dict[str, Any]:
        """Full sync of releases and upcoming dates.

        Args:
            days_ahead: Number of days ahead to sync dates

        Returns:
            Combined sync results
        """
        logger.info("Starting full release calendar sync...")

        releases_result = self.sync_releases()
        dates_result = self.sync_release_dates(days_ahead=days_ahead)

        return {
            "releases": releases_result,
            "dates": dates_result,
        }
