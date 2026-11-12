"""Decide whether a daily sweep was missed while the scheduler was down.

Every daily sweep re-fetches each series' full lookback window and upserts,
so a single successful sweep fills any gap. The scheduler runs one at start
when the last successful sweep is older than the most recent scheduled slot.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

# The daily sweep logs one row per source; both must have succeeded.
SWEEP_SOURCES = ("FRED", "BLS")
SWEEP_JOB_TYPE = "daily_sweep"


def last_sweep_slot(now: datetime, *, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """The most recent scheduled sweep time at or before `now`."""
    local = now.astimezone(tz)
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > local:
        slot -= timedelta(days=1)
    return slot


def sweep_is_overdue(
    last_success: datetime | None,
    now: datetime,
    *,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> bool:
    """True when no sweep has succeeded since the most recent scheduled slot."""
    if last_success is None:
        return True
    return last_success < last_sweep_slot(now, hour=hour, minute=minute, tz=tz)


def last_successful_daily_sweep() -> datetime | None:
    """When every sweep source last completed successfully, or None if one never has."""
    from src.db.connection import get_session
    from src.db.models import FetchLog

    with get_session() as session:
        rows = session.execute(
            select(FetchLog.source, func.max(FetchLog.completed_at))
            .where(
                FetchLog.job_type == SWEEP_JOB_TYPE,
                FetchLog.status == "success",
                FetchLog.source.in_(SWEEP_SOURCES),
            )
            .group_by(FetchLog.source)
        ).all()
    latest = {source: completed for source, completed in rows if completed is not None}
    if set(latest) != set(SWEEP_SOURCES):
        return None
    return min(latest.values())
