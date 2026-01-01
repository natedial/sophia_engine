"""Scheduled job definitions."""

import logging
from datetime import datetime

from src.config import get_settings
from src.db import get_session
from src.db.models import FetchLog, Source

logger = logging.getLogger(__name__)


def daily_sweep_fred() -> dict:
    """Daily sweep of all FRED core series.

    Runs at configured time (default 5pm ET) to refresh all data.
    """
    logger.info("Starting daily FRED sweep")
    started_at = datetime.utcnow()

    try:
        from src.fetchers.fred import FredFetcher

        fetcher = FredFetcher()
        core_series = fetcher.get_core_series()

        results = fetcher.fetch_multiple(list(core_series.keys()))

        success_count = sum(1 for r in results if r["status"] == "success")
        total_records = sum(r.get("records_inserted", 0) for r in results if r["status"] == "success")

        logger.info(
            f"Daily FRED sweep complete: {success_count}/{len(results)} series, "
            f"{total_records} total records"
        )

        return {
            "status": "success",
            "series_fetched": success_count,
            "series_failed": len(results) - success_count,
            "total_records": total_records,
        }

    except Exception as e:
        logger.error(f"Daily FRED sweep failed: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        completed_at = datetime.utcnow()
        _log_sweep("FRED", "daily_sweep", started_at, completed_at)


def daily_sweep_bls() -> dict:
    """Daily sweep of all BLS core series."""
    logger.info("Starting daily BLS sweep")
    started_at = datetime.utcnow()

    try:
        from src.fetchers.bls import BlsFetcher

        fetcher = BlsFetcher()
        results = fetcher.fetch_core_series()

        success_count = sum(1 for r in results if r["status"] == "success")
        total_records = sum(r.get("records_inserted", 0) for r in results if r["status"] == "success")

        logger.info(
            f"Daily BLS sweep complete: {success_count}/{len(results)} series, "
            f"{total_records} total records"
        )

        return {
            "status": "success",
            "series_fetched": success_count,
            "series_failed": len(results) - success_count,
            "total_records": total_records,
        }

    except Exception as e:
        logger.error(f"Daily BLS sweep failed: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        completed_at = datetime.utcnow()
        _log_sweep("BLS", "daily_sweep", started_at, completed_at)


def daily_sweep_all() -> dict:
    """Run daily sweep for all sources."""
    logger.info("Starting daily sweep for all sources")

    results = {
        "fred": daily_sweep_fred(),
        "bls": daily_sweep_bls(),
    }

    success = all(r["status"] == "success" for r in results.values())
    logger.info(f"Daily sweep complete. Overall status: {'success' if success else 'partial failure'}")

    return results


def fetch_series_on_release(source: str, series_ids: list[str], release_name: str) -> dict:
    """Fetch specific series triggered by an economic release.

    Called when a scheduled release (CPI, NFP, etc.) is expected.
    """
    logger.info(f"Release trigger: {release_name} - fetching {len(series_ids)} series from {source}")
    started_at = datetime.utcnow()

    try:
        if source.upper() == "FRED":
            from src.fetchers.fred import FredFetcher
            fetcher = FredFetcher()
        elif source.upper() == "BLS":
            from src.fetchers.bls import BlsFetcher
            fetcher = BlsFetcher()
        else:
            raise ValueError(f"Unknown source: {source}")

        results = fetcher.fetch_multiple(series_ids)

        success_count = sum(1 for r in results if r["status"] == "success")
        total_records = sum(r.get("records_inserted", 0) for r in results if r["status"] == "success")

        logger.info(
            f"Release fetch complete ({release_name}): {success_count}/{len(results)} series, "
            f"{total_records} records"
        )

        return {
            "status": "success",
            "release": release_name,
            "series_fetched": success_count,
            "total_records": total_records,
        }

    except Exception as e:
        logger.error(f"Release fetch failed ({release_name}): {e}")
        return {"status": "error", "release": release_name, "error": str(e)}

    finally:
        completed_at = datetime.utcnow()
        _log_sweep(source, f"release_{release_name}", started_at, completed_at)


def _log_sweep(source: str, job_type: str, started_at: datetime, completed_at: datetime) -> None:
    """Log a sweep operation to the database."""
    try:
        with get_session() as session:
            log = FetchLog(
                started_at=started_at,
                completed_at=completed_at,
                status="completed",
            )
            session.add(log)
    except Exception as e:
        logger.warning(f"Failed to log sweep: {e}")
