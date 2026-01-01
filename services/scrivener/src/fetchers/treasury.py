"""Treasury Fiscal Data API fetcher for auction data."""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from sqlalchemy.dialects.postgresql import insert

from src.config import get_settings
from src.db import get_session
from src.db.models import TreasuryAuction

logger = logging.getLogger(__name__)

# Treasury Fiscal Data API base URL
BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

# Endpoints
AUCTIONS_ENDPOINT = "/v1/accounting/od/auctions_query"
UPCOMING_AUCTIONS_ENDPOINT = "/v1/accounting/od/upcoming_auctions"


class TreasuryFetcher:
    """Fetcher for Treasury auction data from Fiscal Data API."""

    def __init__(self):
        self.settings = get_settings()
        self._client = httpx.Client(timeout=30.0)

    def _make_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to the Treasury Fiscal Data API."""
        url = f"{BASE_URL}{endpoint}"
        params = params or {}

        # Default to JSON format and reasonable page size
        params.setdefault("format", "json")
        params.setdefault("page[size]", 1000)

        response = self._client.get(url, params=params)
        response.raise_for_status()

        return response.json()

    def fetch_auction_results(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        security_type: str | None = None,
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch historical auction results.

        Args:
            start_date: Filter auctions from this date
            end_date: Filter auctions to this date
            security_type: Filter by type (Bill, Note, Bond, TIPS, FRN, CMB)
            page_size: Number of results per page

        Returns:
            List of auction result records
        """
        params: dict[str, Any] = {"page[size]": page_size}

        # Build filter string
        filters = []
        if start_date:
            filters.append(f"auction_date:gte:{start_date.isoformat()}")
        if end_date:
            filters.append(f"auction_date:lte:{end_date.isoformat()}")
        if security_type:
            filters.append(f"security_type:eq:{security_type}")

        if filters:
            params["filter"] = ",".join(filters)

        # Sort by auction date descending
        params["sort"] = "-auction_date"

        all_results = []
        page = 1

        while True:
            params["page[number]"] = page
            data = self._make_request(AUCTIONS_ENDPOINT, params)

            results = data.get("data", [])
            if not results:
                break

            all_results.extend(results)

            # Check if there are more pages
            meta = data.get("meta", {})
            total_pages = meta.get("total-pages", 1)
            if page >= total_pages:
                break

            page += 1

        logger.info(f"Fetched {len(all_results)} auction results")
        return all_results

    def fetch_upcoming_auctions(self) -> list[dict[str, Any]]:
        """Fetch upcoming Treasury auctions.

        Returns:
            List of upcoming auction announcements
        """
        params = {
            "sort": "auction_date",
            "page[size]": 100,
        }

        data = self._make_request(UPCOMING_AUCTIONS_ENDPOINT, params)
        results = data.get("data", [])

        logger.info(f"Fetched {len(results)} upcoming auctions")
        return results

    def fetch_recent_auctions(
        self,
        days: int = 30,
        security_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch auctions from the last N days.

        Args:
            days: Number of days to look back
            security_type: Optional filter by security type

        Returns:
            List of recent auction results
        """
        end_date = date.today()
        start_date = date.today() - __import__("datetime").timedelta(days=days)

        return self.fetch_auction_results(
            start_date=start_date,
            end_date=end_date,
            security_type=security_type,
        )

    def fetch_auctions_by_cusip(self, cusip: str) -> list[dict[str, Any]]:
        """Fetch auction history for a specific CUSIP.

        Args:
            cusip: The 9-character CUSIP identifier

        Returns:
            List of auction records for that CUSIP
        """
        params = {
            "filter": f"cusip:eq:{cusip}",
            "sort": "-auction_date",
        }

        data = self._make_request(AUCTIONS_ENDPOINT, params)
        return data.get("data", [])

    def parse_auction_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Parse a raw auction record into a cleaner format.

        Converts string values to appropriate types.
        """

        def safe_decimal(val: str | None) -> Decimal | None:
            if val is None or val == "" or val == "null":
                return None
            try:
                return Decimal(val)
            except:
                return None

        def safe_date(val: str | None) -> date | None:
            if val is None or val == "" or val == "null":
                return None
            try:
                return date.fromisoformat(val)
            except:
                return None

        def safe_int(val: str | None) -> int | None:
            if val is None or val == "" or val == "null":
                return None
            try:
                return int(val)
            except:
                return None

        return {
            "cusip": record.get("cusip"),
            "security_type": record.get("security_type"),
            "security_term": record.get("security_term"),
            "auction_date": safe_date(record.get("auction_date")),
            "issue_date": safe_date(record.get("issue_date")),
            "maturity_date": safe_date(record.get("maturity_date")),
            "high_yield": safe_decimal(record.get("high_investment_rate")),
            "high_discount_rate": safe_decimal(record.get("high_discount_rate")),
            "bid_to_cover_ratio": safe_decimal(record.get("bid_to_cover_ratio")),
            "total_accepted": safe_decimal(record.get("total_accepted")),
            "total_tendered": safe_decimal(record.get("total_tendered")),
            "competitive_accepted": safe_decimal(record.get("competitive_accepted")),
            "noncompetitive_accepted": safe_decimal(record.get("noncompetitive_accepted")),
            "primary_dealer_accepted": safe_decimal(record.get("primary_dealer_accepted")),
            "direct_bidder_accepted": safe_decimal(record.get("direct_bidder_accepted")),
            "indirect_bidder_accepted": safe_decimal(record.get("indirect_bidder_accepted")),
            "offering_amount": safe_decimal(record.get("offering_amt")),
            "reopening": record.get("reopening") == "Yes",
            "original_cusip": record.get("original_cusip"),
        }

    @staticmethod
    def get_security_types() -> list[str]:
        """Get list of Treasury security types."""
        return ["Bill", "Note", "Bond", "TIPS", "FRN", "CMB"]

    def store_auctions(self, records: list[dict[str, Any]]) -> int:
        """Store auction records in the database.

        Uses upsert to handle duplicates based on cusip + auction_date.

        Args:
            records: Raw records from the API

        Returns:
            Number of records upserted
        """
        if not records:
            return 0

        parsed = [self.parse_auction_record(r) for r in records]
        # Filter out records without required fields
        valid = [p for p in parsed if p["cusip"] and p["auction_date"]]

        if not valid:
            return 0

        with get_session() as session:
            stmt = insert(TreasuryAuction).values(valid)
            stmt = stmt.on_conflict_do_update(
                index_elements=["cusip", "auction_date"],
                set_={
                    "high_yield": stmt.excluded.high_yield,
                    "high_discount_rate": stmt.excluded.high_discount_rate,
                    "bid_to_cover_ratio": stmt.excluded.bid_to_cover_ratio,
                    "total_accepted": stmt.excluded.total_accepted,
                    "total_tendered": stmt.excluded.total_tendered,
                    "offering_amount": stmt.excluded.offering_amount,
                },
            )
            session.execute(stmt)

        logger.info(f"Stored {len(valid)} auction records")
        return len(valid)

    def fetch_and_store(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        security_type: str | None = None,
    ) -> dict[str, Any]:
        """Fetch auction data and store in database.

        Args:
            start_date: Start of date range
            end_date: End of date range
            security_type: Filter by security type

        Returns:
            Summary of fetch operation
        """
        start_date = start_date or (date.today() - __import__("datetime").timedelta(days=365 * 5))
        end_date = end_date or date.today()

        logger.info(f"Fetching Treasury auctions from {start_date} to {end_date}")

        try:
            records = self.fetch_auction_results(
                start_date=start_date,
                end_date=end_date,
                security_type=security_type,
            )

            stored = self.store_auctions(records)

            return {
                "status": "success",
                "records_fetched": len(records),
                "records_stored": stored,
                "start_date": str(start_date),
                "end_date": str(end_date),
            }

        except Exception as e:
            logger.error(f"Error fetching Treasury auctions: {e}")
            return {
                "status": "error",
                "error": str(e),
            }
