"""Query utilities for Treasury auction data."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, desc

from src.db import get_session
from src.db.models import TreasuryAuction


class AuctionQuery:
    """Query interface for Treasury auction data."""

    @staticmethod
    def get_recent(
        days: int = 30,
        security_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Get recent auction results.

        Args:
            days: Number of days to look back
            security_type: Filter by type (Bill, Note, Bond, TIPS, FRN)
            limit: Max results to return

        Returns:
            List of auction records
        """
        cutoff = date.today() - timedelta(days=days)

        with get_session() as session:
            query = session.query(TreasuryAuction).filter(
                TreasuryAuction.auction_date >= cutoff
            )

            if security_type:
                query = query.filter(TreasuryAuction.security_type == security_type)

            query = query.order_by(desc(TreasuryAuction.auction_date))

            if limit:
                query = query.limit(limit)

            results = query.all()

            return [AuctionQuery._to_dict(a) for a in results]

    @staticmethod
    def get_by_cusip(cusip: str) -> list[dict]:
        """Get auction history for a specific CUSIP.

        Args:
            cusip: 9-character CUSIP identifier

        Returns:
            List of auction records for that security
        """
        with get_session() as session:
            results = (
                session.query(TreasuryAuction)
                .filter(TreasuryAuction.cusip == cusip)
                .order_by(desc(TreasuryAuction.auction_date))
                .all()
            )

            return [AuctionQuery._to_dict(a) for a in results]

    @staticmethod
    def get_by_date_range(
        start_date: date,
        end_date: date,
        security_type: str | None = None,
    ) -> list[dict]:
        """Get auctions within a date range.

        Args:
            start_date: Start of range
            end_date: End of range
            security_type: Optional type filter

        Returns:
            List of auction records
        """
        with get_session() as session:
            query = session.query(TreasuryAuction).filter(
                and_(
                    TreasuryAuction.auction_date >= start_date,
                    TreasuryAuction.auction_date <= end_date,
                )
            )

            if security_type:
                query = query.filter(TreasuryAuction.security_type == security_type)

            results = query.order_by(TreasuryAuction.auction_date).all()

            return [AuctionQuery._to_dict(a) for a in results]

    @staticmethod
    def get_latest_by_term(security_type: str, term: str) -> dict | None:
        """Get the most recent auction for a specific security type and term.

        Args:
            security_type: Bill, Note, Bond, etc.
            term: e.g., '10-Year', '2-Year', '13-Week'

        Returns:
            Most recent auction for that security, or None
        """
        with get_session() as session:
            result = (
                session.query(TreasuryAuction)
                .filter(
                    and_(
                        TreasuryAuction.security_type == security_type,
                        TreasuryAuction.security_term.ilike(f"%{term}%"),
                    )
                )
                .order_by(desc(TreasuryAuction.auction_date))
                .first()
            )

            return AuctionQuery._to_dict(result) if result else None

    @staticmethod
    def get_yield_history(
        security_type: str,
        term: str,
        days: int = 365,
    ) -> list[dict]:
        """Get yield history for a specific security type/term.

        Args:
            security_type: Bill, Note, Bond, etc.
            term: e.g., '10-Year', '2-Year'
            days: Number of days of history

        Returns:
            List of {date, yield} records
        """
        cutoff = date.today() - timedelta(days=days)

        with get_session() as session:
            results = (
                session.query(TreasuryAuction)
                .filter(
                    and_(
                        TreasuryAuction.security_type == security_type,
                        TreasuryAuction.security_term.ilike(f"%{term}%"),
                        TreasuryAuction.auction_date >= cutoff,
                        TreasuryAuction.high_yield.isnot(None),
                    )
                )
                .order_by(TreasuryAuction.auction_date)
                .all()
            )

            return [
                {
                    "date": r.auction_date.isoformat(),
                    "yield": float(r.high_yield),
                    "bid_to_cover": float(r.bid_to_cover_ratio) if r.bid_to_cover_ratio else None,
                }
                for r in results
            ]

    @staticmethod
    def get_summary_stats(
        security_type: str | None = None,
        days: int = 30,
    ) -> dict:
        """Get summary statistics for recent auctions.

        Args:
            security_type: Optional type filter
            days: Number of days to analyze

        Returns:
            Summary statistics
        """
        cutoff = date.today() - timedelta(days=days)

        with get_session() as session:
            query = session.query(TreasuryAuction).filter(
                TreasuryAuction.auction_date >= cutoff
            )

            if security_type:
                query = query.filter(TreasuryAuction.security_type == security_type)

            results = query.all()

            if not results:
                return {"count": 0}

            yields = [float(r.high_yield) for r in results if r.high_yield]
            btc_ratios = [float(r.bid_to_cover_ratio) for r in results if r.bid_to_cover_ratio]
            total_offered = sum(float(r.offering_amount) for r in results if r.offering_amount)

            return {
                "count": len(results),
                "period_days": days,
                "total_offered_millions": round(total_offered / 1_000_000, 2) if total_offered else 0,
                "avg_yield": round(sum(yields) / len(yields), 4) if yields else None,
                "min_yield": round(min(yields), 4) if yields else None,
                "max_yield": round(max(yields), 4) if yields else None,
                "avg_bid_to_cover": round(sum(btc_ratios) / len(btc_ratios), 2) if btc_ratios else None,
                "by_type": AuctionQuery._count_by_type(results),
            }

    @staticmethod
    def _count_by_type(auctions: list) -> dict[str, int]:
        """Count auctions by security type."""
        counts: dict[str, int] = {}
        for a in auctions:
            counts[a.security_type] = counts.get(a.security_type, 0) + 1
        return counts

    @staticmethod
    def _to_dict(auction: TreasuryAuction) -> dict:
        """Convert auction model to dict."""

        def to_float(val: Decimal | None) -> float | None:
            return float(val) if val is not None else None

        return {
            "cusip": auction.cusip,
            "security_type": auction.security_type,
            "security_term": auction.security_term,
            "auction_date": auction.auction_date.isoformat(),
            "issue_date": auction.issue_date.isoformat() if auction.issue_date else None,
            "maturity_date": auction.maturity_date.isoformat() if auction.maturity_date else None,
            "high_yield": to_float(auction.high_yield),
            "high_discount_rate": to_float(auction.high_discount_rate),
            "bid_to_cover_ratio": to_float(auction.bid_to_cover_ratio),
            "offering_amount": to_float(auction.offering_amount),
            "total_accepted": to_float(auction.total_accepted),
            "total_tendered": to_float(auction.total_tendered),
            "primary_dealer_accepted": to_float(auction.primary_dealer_accepted),
            "direct_bidder_accepted": to_float(auction.direct_bidder_accepted),
            "indirect_bidder_accepted": to_float(auction.indirect_bidder_accepted),
            "reopening": auction.reopening,
        }
