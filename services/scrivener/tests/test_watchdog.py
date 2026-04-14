from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.monitor.watchdog import AlertState, ServiceIssue, assess_service, should_send_alert


def test_assess_service_flags_non_running_container() -> None:
    issue = assess_service(
        "api",
        {
            "RestartCount": 4,
            "State": {
                "Status": "restarting",
                "ExitCode": 2,
                "StartedAt": "2026-04-01T00:00:00Z",
                "FinishedAt": "2026-04-01T00:01:00Z",
            },
        },
        logs="Invalid value for '--port'",
    )

    assert issue is not None
    assert issue.summary == "Service 'api' is restarting"
    assert "restart:4" in issue.fingerprint
    assert "Invalid value for '--port'" in issue.logs


def test_assess_service_flags_unhealthy_container() -> None:
    issue = assess_service(
        "api",
        {
            "RestartCount": 0,
            "State": {
                "Status": "running",
                "ExitCode": 0,
                "StartedAt": "2026-04-01T00:00:00Z",
                "FinishedAt": "0001-01-01T00:00:00Z",
                "Health": {"Status": "unhealthy"},
            },
        },
    )

    assert issue is not None
    assert issue.summary == "Service 'api' is unhealthy"


def test_should_send_alert_for_new_issue() -> None:
    issue = ServiceIssue(
        service="api",
        fingerprint="status:restarting",
        summary="Service 'api' is restarting",
        details={},
        logs="",
    )

    assert should_send_alert(
        None,
        issue,
        current_time=datetime(2026, 4, 1, tzinfo=UTC),
        cooldown=timedelta(minutes=60),
    )


def test_should_not_resend_same_issue_within_cooldown() -> None:
    issue = ServiceIssue(
        service="api",
        fingerprint="status:restarting",
        summary="Service 'api' is restarting",
        details={},
        logs="",
    )
    existing = AlertState(
        fingerprint="status:restarting",
        last_alerted_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC).isoformat(),
    )

    assert not should_send_alert(
        existing,
        issue,
        current_time=datetime(2026, 4, 1, 12, 30, tzinfo=UTC),
        cooldown=timedelta(minutes=60),
    )


def test_should_resend_after_cooldown_or_fingerprint_change() -> None:
    issue = ServiceIssue(
        service="api",
        fingerprint="status:exited",
        summary="Service 'api' is exited",
        details={},
        logs="",
    )
    existing = AlertState(
        fingerprint="status:restarting",
        last_alerted_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC).isoformat(),
    )

    assert should_send_alert(
        existing,
        issue,
        current_time=datetime(2026, 4, 1, 12, 5, tzinfo=UTC),
        cooldown=timedelta(minutes=60),
    )
