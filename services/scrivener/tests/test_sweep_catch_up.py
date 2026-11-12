"""A missed daily sweep is run as soon as the scheduler starts.

Every daily sweep re-fetches the full lookback window and upserts, so one
successful sweep fills any gap left while the host was down.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.scheduler.catch_up import last_sweep_slot, sweep_is_overdue

ET = ZoneInfo("America/New_York")


def test_slot_is_today_after_sweep_time() -> None:
    now = datetime(2026, 11, 12, 18, 30, tzinfo=ET)
    assert last_sweep_slot(now, hour=17, minute=0, tz=ET) == datetime(
        2026, 11, 12, 17, 0, tzinfo=ET
    )


def test_slot_is_yesterday_before_sweep_time() -> None:
    now = datetime(2026, 11, 12, 9, 0, tzinfo=ET)
    assert last_sweep_slot(now, hour=17, minute=0, tz=ET) == datetime(
        2026, 11, 11, 17, 0, tzinfo=ET
    )


def test_never_swept_is_overdue() -> None:
    now = datetime(2026, 11, 12, 9, 0, tzinfo=ET)
    assert sweep_is_overdue(None, now, hour=17, minute=0, tz=ET)


def test_sweep_before_last_slot_is_overdue() -> None:
    now = datetime(2026, 11, 12, 18, 30, tzinfo=ET)
    last = datetime(2026, 11, 11, 17, 4, tzinfo=ET)
    assert sweep_is_overdue(last, now, hour=17, minute=0, tz=ET)


def test_sweep_after_last_slot_is_not_overdue() -> None:
    now = datetime(2026, 11, 12, 9, 0, tzinfo=ET)
    last = datetime(2026, 11, 11, 17, 6, tzinfo=ET)
    assert not sweep_is_overdue(last, now, hour=17, minute=0, tz=ET)


def test_comparison_works_across_time_zones() -> None:
    """fetch_logs stores UTC; the schedule is in Eastern time."""
    now = datetime(2026, 11, 12, 18, 30, tzinfo=ET)
    last_utc = datetime(2026, 11, 12, 22, 5, tzinfo=ZoneInfo("UTC"))  # 17:05 ET
    assert not sweep_is_overdue(last_utc, now, hour=17, minute=0, tz=ET)


def _offline_runner(monkeypatch, *, last_sweep=None, calendar_ready=True, calls=None):
    """A runner whose database and network touch points are stubbed out."""
    from src.query.releases import ReleaseQuery
    from src.scheduler import runner as runner_module

    calls = calls if calls is not None else []
    monkeypatch.setattr(runner_module, "last_successful_daily_sweep", lambda: last_sweep)
    monkeypatch.setattr(runner_module, "has_upcoming_release_dates", lambda days: calendar_ready)
    monkeypatch.setattr(
        ReleaseQuery,
        "_auto_sync_release_calendar",
        staticmethod(lambda days_ahead: calls.append(("sync", days_ahead)) or True),
    )
    runner = runner_module.SchedulerRunner(blocking=False)
    monkeypatch.setattr(runner, "_check_and_schedule_events", lambda: calls.append(("check",)))
    monkeypatch.setattr(runner, "_sync_speaker_calendar", lambda: None)
    monkeypatch.setattr(runner.scheduler, "start", lambda: None)
    return runner


def test_runner_start_runs_overdue_sweep_immediately(monkeypatch) -> None:
    runner = _offline_runner(monkeypatch, last_sweep=None)

    runner.start()

    ids = {job.id for job in runner.scheduler.get_jobs()}
    assert "catch_up_sweep" in ids


def test_runner_start_skips_catch_up_when_current(monkeypatch) -> None:
    runner = _offline_runner(monkeypatch, last_sweep=datetime.now(ET))

    runner.start()

    ids = {job.id for job in runner.scheduler.get_jobs()}
    assert "catch_up_sweep" not in ids


def test_runner_schedules_daily_release_calendar_sync(monkeypatch) -> None:
    runner = _offline_runner(monkeypatch, last_sweep=datetime.now(ET))

    runner.start()

    job = runner.scheduler.get_job("release_calendar_sync")
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "5"
    assert fields["minute"] == "50"


def test_daily_release_sync_looks_120_days_ahead(monkeypatch) -> None:
    calls: list = []
    runner = _offline_runner(monkeypatch, last_sweep=datetime.now(ET), calls=calls)

    runner._sync_release_calendar()

    assert ("sync", 120) in calls


def test_start_syncs_empty_release_calendar_before_first_check(monkeypatch) -> None:
    calls: list = []
    runner = _offline_runner(
        monkeypatch, last_sweep=datetime.now(ET), calendar_ready=False, calls=calls
    )

    runner.start()

    assert calls.index(("sync", 120)) < calls.index(("check",))


def test_start_skips_release_sync_when_calendar_has_dates(monkeypatch) -> None:
    calls: list = []
    runner = _offline_runner(
        monkeypatch, last_sweep=datetime.now(ET), calendar_ready=True, calls=calls
    )

    runner.start()

    assert ("sync", 120) not in calls
