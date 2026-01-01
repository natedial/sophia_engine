"""BLS (Bureau of Labor Statistics) fetcher."""

import logging
from datetime import date
from typing import Any

import httpx

from src.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)


# BLS series IDs follow specific patterns
# Reference: https://www.bls.gov/help/hlpforma.htm
CORE_SERIES = {
    # Employment Situation (Current Employment Statistics - CES)
    "CES0000000001": "Total Nonfarm Payrolls (thousands)",
    "CES0500000001": "Total Private Payrolls (thousands)",
    "CES0500000003": "Average Weekly Hours, Private",
    "CES0500000011": "Average Hourly Earnings, Private",

    # Employment Situation (Current Population Survey - LNS)
    "LNS14000000": "Unemployment Rate",
    "LNS11000000": "Civilian Labor Force Level",
    "LNS12000000": "Employment Level",
    "LNS13000000": "Unemployment Level",
    "LNS11300000": "Labor Force Participation Rate",
    "LNS12300000": "Employment-Population Ratio",

    # Consumer Price Index (CPI-U)
    "CUSR0000SA0": "CPI-U All Items (seasonally adjusted)",
    "CUSR0000SA0L1E": "CPI-U Core (Less Food & Energy, SA)",
    "CUSR0000SAF1": "CPI-U Food",
    "CUSR0000SETA01": "CPI-U New Vehicles",
    "CUSR0000SETA02": "CPI-U Used Vehicles",
    "CUSR0000SAH1": "CPI-U Shelter",
    "CUSR0000SETB01": "CPI-U Gasoline",

    # CPI-U (not seasonally adjusted, for YoY calculations)
    "CUUR0000SA0": "CPI-U All Items (NSA)",
    "CUUR0000SA0L1E": "CPI-U Core (Less Food & Energy, NSA)",

    # Producer Price Index (PPI)
    "WPSFD4": "PPI Final Demand",
    "WPSFD49104": "PPI Final Demand Less Foods & Energy",
    "WPSFD41": "PPI Final Demand Goods",
    "WPSFD42": "PPI Final Demand Services",

    # Employment Cost Index
    "CIU1010000000000A": "ECI Total Compensation, All Workers",
    "CIU2010000000000A": "ECI Wages & Salaries, All Workers",

    # JOLTS (Job Openings and Labor Turnover Survey)
    "JTS000000000000000JOL": "Job Openings Level",
    "JTS000000000000000HIL": "Hires Level",
    "JTS000000000000000TSL": "Total Separations Level",
    "JTS000000000000000QUL": "Quits Level",
    "JTS000000000000000LDL": "Layoffs & Discharges Level",
    "JTS000000000000000JOR": "Job Openings Rate",
    "JTS000000000000000QUR": "Quits Rate",

    # Weekly Claims (from ETA but often accessed via BLS)
    # Note: Initial claims are better sourced from DOL/FRED

    # Import/Export Prices
    "EIUIR": "Import Price Index",
    "EIUIQ": "Export Price Index",

    # Productivity
    "PRS85006092": "Nonfarm Business Labor Productivity",
    "PRS85006112": "Nonfarm Business Unit Labor Costs",
}

# Series metadata for display names and categories
SERIES_METADATA = {
    "CES0000000001": {"category": "employment", "frequency": "monthly"},
    "LNS14000000": {"category": "employment", "frequency": "monthly"},
    "CUSR0000SA0": {"category": "inflation", "frequency": "monthly"},
    "WPSFD4": {"category": "inflation", "frequency": "monthly"},
    "JTS000000000000000JOL": {"category": "labor", "frequency": "monthly"},
}


class BlsFetcher(BaseFetcher):
    """Fetcher for BLS (Bureau of Labor Statistics) data."""

    source_name = "BLS"
    base_url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    rate_limit_per_min = 25  # Conservative limit

    def __init__(self) -> None:
        super().__init__()
        self._client = httpx.Client(timeout=30.0)
        # BLS API key is optional but increases limits
        self._has_api_key = bool(self.settings.bls_api_key)
        if not self._has_api_key:
            logger.warning(
                "BLS_API_KEY not set. Using unregistered access (500 req/day, 25 series/request). "
                "Register at https://data.bls.gov/registrationEngine/"
            )

    def _make_request(
        self,
        series_ids: list[str],
        start_year: int,
        end_year: int,
    ) -> dict[str, Any]:
        """Make a request to the BLS API."""
        payload: dict[str, Any] = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }

        if self._has_api_key:
            payload["registrationkey"] = self.settings.bls_api_key
            # With API key, can request catalog data
            payload["catalog"] = True

        headers = {"Content-Type": "application/json"}

        response = self._client.post(
            self.base_url,
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

        data = response.json()

        if data.get("status") != "REQUEST_SUCCEEDED":
            error_msg = "; ".join(data.get("message", ["Unknown error"]))
            raise ValueError(f"BLS API error: {error_msg}")

        return data

    def fetch_series_info(self, external_id: str) -> dict[str, Any]:
        """Fetch series metadata from BLS.

        Note: BLS doesn't have a dedicated metadata endpoint.
        We use catalog data from a minimal data request or fall back to our mapping.
        """
        # Try to get catalog info via API if we have a key
        if self._has_api_key:
            try:
                current_year = date.today().year
                data = self._make_request([external_id], current_year, current_year)

                if data.get("Results", {}).get("series"):
                    series_data = data["Results"]["series"][0]
                    catalog = series_data.get("catalog", {})

                    return {
                        "name": catalog.get("series_title", CORE_SERIES.get(external_id, external_id)),
                        "description": catalog.get("series_title"),
                        "frequency": self._parse_frequency(catalog.get("survey_abbreviation")),
                        "units": catalog.get("series_title"),  # BLS doesn't separate units well
                        "seasonal_adjustment": catalog.get("seasonality"),
                        "metadata": {
                            "bls_id": external_id,
                            "survey": catalog.get("survey_name"),
                            "survey_abbr": catalog.get("survey_abbreviation"),
                            "area": catalog.get("area_name"),
                            "measure": catalog.get("measure_text"),
                        },
                    }
            except Exception as e:
                logger.debug(f"Could not fetch catalog for {external_id}: {e}")

        # Fall back to our static mapping
        return {
            "name": CORE_SERIES.get(external_id, external_id),
            "description": CORE_SERIES.get(external_id),
            "frequency": SERIES_METADATA.get(external_id, {}).get("frequency", "monthly"),
            "units": None,
            "seasonal_adjustment": "SA" if "S" in external_id[4:6] else "NSA",
            "metadata": {"bls_id": external_id},
        }

    def _parse_frequency(self, survey_abbr: str | None) -> str:
        """Parse frequency from BLS survey abbreviation."""
        # Most BLS data is monthly
        quarterly_surveys = {"ECI", "PR"}
        if survey_abbr in quarterly_surveys:
            return "quarterly"
        return "monthly"

    def _parse_period(self, period: str, year: int) -> date | None:
        """Parse BLS period code to date.

        BLS uses:
        - M01-M12 for monthly data
        - Q01-Q04 for quarterly data
        - A01 for annual data
        - S01-S02 for semi-annual
        """
        if period.startswith("M"):
            month = int(period[1:])
            if 1 <= month <= 12:
                return date(year, month, 1)
        elif period.startswith("Q"):
            quarter = int(period[1:])
            month = (quarter - 1) * 3 + 1
            return date(year, month, 1)
        elif period.startswith("A"):
            return date(year, 1, 1)
        elif period.startswith("S"):
            half = int(period[1:])
            month = 1 if half == 1 else 7
            return date(year, month, 1)

        logger.warning(f"Unknown period format: {period}")
        return None

    def fetch_observations(
        self,
        external_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch observations from BLS."""
        start_date = start_date or self.get_default_start_date()
        end_date = end_date or date.today()

        start_year = start_date.year
        end_year = end_date.year

        # BLS API limits to 20 years per request
        all_observations = []

        while start_year <= end_year:
            chunk_end_year = min(start_year + 19, end_year)

            data = self._make_request([external_id], start_year, chunk_end_year)

            if data.get("Results", {}).get("series"):
                series_data = data["Results"]["series"][0]

                for obs in series_data.get("data", []):
                    year = int(obs["year"])
                    period = obs["period"]

                    # Skip annual averages (M13)
                    if period == "M13":
                        continue

                    obs_date = self._parse_period(period, year)
                    if obs_date is None:
                        continue

                    # Filter by date range
                    if not (start_date <= obs_date <= end_date):
                        continue

                    value = obs.get("value")
                    if value == "-" or value is None:
                        continue

                    all_observations.append({
                        "date": obs_date,
                        "value": float(value),
                    })

            start_year = chunk_end_year + 1

        # Sort by date (BLS returns most recent first)
        all_observations.sort(key=lambda x: x["date"])

        return all_observations

    def fetch_multiple_series_batch(
        self,
        external_ids: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch multiple series in a single API call (more efficient).

        BLS allows up to 25 series per request (50 with API key).
        """
        start_date = start_date or self.get_default_start_date()
        end_date = end_date or date.today()

        max_series = 50 if self._has_api_key else 25
        results: dict[str, list[dict[str, Any]]] = {sid: [] for sid in external_ids}

        # Process in chunks
        for i in range(0, len(external_ids), max_series):
            chunk_ids = external_ids[i:i + max_series]

            start_year = start_date.year
            end_year = end_date.year

            while start_year <= end_year:
                chunk_end_year = min(start_year + 19, end_year)

                try:
                    data = self._make_request(chunk_ids, start_year, chunk_end_year)

                    for series_data in data.get("Results", {}).get("series", []):
                        series_id = series_data.get("seriesID")
                        if series_id not in results:
                            continue

                        for obs in series_data.get("data", []):
                            year = int(obs["year"])
                            period = obs["period"]

                            if period == "M13":
                                continue

                            obs_date = self._parse_period(period, year)
                            if obs_date is None:
                                continue

                            if not (start_date <= obs_date <= end_date):
                                continue

                            value = obs.get("value")
                            if value == "-" or value is None:
                                continue

                            results[series_id].append({
                                "date": obs_date,
                                "value": float(value),
                            })

                except Exception as e:
                    logger.error(f"Error fetching batch: {e}")

                start_year = chunk_end_year + 1

        # Sort all results
        for series_id in results:
            results[series_id].sort(key=lambda x: x["date"])

        return results

    @classmethod
    def get_core_series(cls) -> dict[str, str]:
        """Get the dictionary of core BLS series."""
        return CORE_SERIES.copy()

    def fetch_core_series(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all core series using batch API for efficiency."""
        series_ids = list(CORE_SERIES.keys())

        # Use batch fetch for efficiency
        batch_results = self.fetch_multiple_series_batch(
            series_ids, start_date, end_date
        )

        results = []
        for external_id, observations in batch_results.items():
            if observations:
                # Ensure series exists
                series_id = self.ensure_series(external_id)
                records_inserted = self.upsert_observations(series_id, observations)

                results.append({
                    "status": "success",
                    "series_id": series_id,
                    "external_id": external_id,
                    "records_fetched": len(observations),
                    "records_inserted": records_inserted,
                })
                logger.info(f"Stored {records_inserted} observations for {external_id}")
            else:
                results.append({
                    "status": "error",
                    "external_id": external_id,
                    "error": "No data returned",
                })

        return results

    @classmethod
    def get_series_by_category(cls, category: str) -> dict[str, str]:
        """Get series filtered by category."""
        return {
            sid: name
            for sid, name in CORE_SERIES.items()
            if SERIES_METADATA.get(sid, {}).get("category") == category
        }
