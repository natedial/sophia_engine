"""Core scheduler setup using APScheduler."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from src.config import get_settings

logger = logging.getLogger(__name__)


def create_scheduler(blocking: bool = True) -> BlockingScheduler | BackgroundScheduler:
    """Create and configure the APScheduler instance.

    Args:
        blocking: If True, returns BlockingScheduler (for standalone process).
                  If False, returns BackgroundScheduler (for integration).
    """
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)

    jobstores = {
        "default": MemoryJobStore(),
    }

    executors = {
        "default": ThreadPoolExecutor(max_workers=5),
    }

    job_defaults = {
        "coalesce": True,  # Combine multiple missed runs into one
        "max_instances": 1,  # Only one instance of each job at a time
        "misfire_grace_time": 60 * 5,  # 5 minute grace period for missed jobs
    }

    scheduler_class = BlockingScheduler if blocking else BackgroundScheduler

    scheduler = scheduler_class(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone=tz,
    )

    return scheduler


def get_timezone() -> ZoneInfo:
    """Get the configured timezone."""
    settings = get_settings()
    return ZoneInfo(settings.timezone)
