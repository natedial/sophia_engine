"""Main scheduler runner that coordinates all jobs."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from src.config import get_settings
from src.scheduler.scheduler import create_scheduler, get_timezone
from src.scheduler.jobs import daily_sweep_all, fetch_series_on_release
from src.scheduler.calendar import EconomicEventsCalendar

logger = logging.getLogger(__name__)


class SchedulerRunner:
    """Main scheduler runner that manages all scheduled jobs."""

    def __init__(self, blocking: bool = True):
        self.settings = get_settings()
        self.scheduler = create_scheduler(blocking=blocking)
        self.events_calendar = EconomicEventsCalendar()
        self.tz = get_timezone()
        self._scheduled_event_ids: set[str] = set()

    def setup_daily_sweep(self) -> None:
        """Set up the daily 5pm sweep job."""
        hour = self.settings.daily_sweep_hour
        minute = self.settings.daily_sweep_minute

        self.scheduler.add_job(
            daily_sweep_all,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=self.tz),
            id="daily_sweep_all",
            name="Daily sweep - all sources",
            replace_existing=True,
        )
        logger.info(f"Scheduled daily sweep at {hour:02d}:{minute:02d} {self.settings.timezone}")

    def setup_calendar_checker(self) -> None:
        """Set up a job to check the economic_events table every 12 hours."""
        # Check at 6am and 6pm ET to pick up the day's events
        self.scheduler.add_job(
            self._check_and_schedule_events,
            trigger=CronTrigger(hour="6,18", minute=0, timezone=self.tz),
            id="calendar_checker",
            name="Economic events checker",
            replace_existing=True,
        )
        logger.info("Scheduled economic events checker (6am & 6pm ET)")

    def _check_and_schedule_events(self) -> None:
        """Check economic_events table for upcoming releases and schedule fetch jobs."""
        now = datetime.now(self.tz)
        # Look ahead 14 hours to catch all events until next check
        window_end = now + timedelta(hours=14)

        try:
            upcoming = self.events_calendar.get_upcoming_events(start=now, end=window_end)
        except Exception as e:
            logger.error(f"Failed to fetch upcoming events: {e}")
            return

        for event in upcoming:
            event_id = event["id"]
            event_name = event["event_name"]
            release_type = event["release_type"]
            scheduled_time = event["scheduled_time"]
            bls_series = event["bls_series"]
            fred_series = event["fred_series"]

            # Skip if already scheduled or already has results
            if event_id in self._scheduled_event_ids:
                continue
            if event.get("has_result"):
                continue

            # Schedule fetch 1 minute after release time
            fetch_time = scheduled_time + timedelta(minutes=1)

            # Skip if fetch time is in the past
            if fetch_time <= now:
                continue

            job_id_base = f"event_{event_id}"

            # Schedule FRED series fetch
            if fred_series:
                self.scheduler.add_job(
                    fetch_series_on_release,
                    trigger=DateTrigger(run_date=fetch_time, timezone=self.tz),
                    args=["FRED", fred_series, f"{release_type} ({event_name})"],
                    id=f"{job_id_base}_fred",
                    name=f"Event fetch: {event_name} (FRED)",
                )
                logger.info(f"Scheduled FRED fetch for '{event_name}' at {fetch_time}")

            # Schedule BLS series fetch
            if bls_series:
                self.scheduler.add_job(
                    fetch_series_on_release,
                    trigger=DateTrigger(run_date=fetch_time, timezone=self.tz),
                    args=["BLS", bls_series, f"{release_type} ({event_name})"],
                    id=f"{job_id_base}_bls",
                    name=f"Event fetch: {event_name} (BLS)",
                )
                logger.info(f"Scheduled BLS fetch for '{event_name}' at {fetch_time}")

            self._scheduled_event_ids.add(event_id)

    def list_jobs(self) -> list[dict]:
        """List all scheduled jobs."""
        now = datetime.now(self.tz)
        jobs = []
        for job in self.scheduler.get_jobs():
            # Calculate next run from trigger if not yet scheduled
            next_run = getattr(job, "next_run_time", None)
            if next_run is None and job.trigger:
                next_run = job.trigger.get_next_fire_time(None, now)
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run,
            })
        return jobs

    def start(self) -> None:
        """Start the scheduler."""
        self.setup_daily_sweep()
        self.setup_calendar_checker()

        # Run initial check
        self._check_and_schedule_events()

        job_count = len(self.scheduler.get_jobs())
        logger.info(f"Starting scheduler with {job_count} jobs...")

        # Log jobs before start (using trigger to calculate next run)
        for job in self.list_jobs():
            logger.info(f"  - {job['name']}: next run {job['next_run']}")

        self.scheduler.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        self.scheduler.shutdown(wait=True)
