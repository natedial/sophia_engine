"""Host-side watchdog for Scrivener Docker services.

Runs outside the app containers and inspects Docker Compose service state so it
can alert on crash loops and unhealthy containers.
"""

from __future__ import annotations

import json
import os
import smtplib
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any


DEFAULT_SERVICES = ("api", "scheduler")
DEFAULT_LOG_LINES = 40
DEFAULT_COOLDOWN_MINUTES = 60


@dataclass
class EmailConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    from_address: str
    to_addresses: list[str]
    use_tls: bool
    subject_prefix: str


@dataclass
class ServiceIssue:
    service: str
    fingerprint: str
    summary: str
    details: dict[str, Any]
    logs: str


@dataclass
class AlertState:
    fingerprint: str
    last_alerted_at: str


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def load_email_config() -> EmailConfig | None:
    host = os.getenv("SCRIVENER_ALERT_SMTP_HOST", "").strip()
    from_address = os.getenv("SCRIVENER_ALERT_FROM", "").strip()
    to_addresses = parse_csv(os.getenv("SCRIVENER_ALERT_TO"))
    if not host or not from_address or not to_addresses:
        return None
    return EmailConfig(
        host=host,
        port=int(os.getenv("SCRIVENER_ALERT_SMTP_PORT", "587")),
        username=os.getenv("SCRIVENER_ALERT_SMTP_USERNAME") or None,
        password=os.getenv("SCRIVENER_ALERT_SMTP_PASSWORD") or None,
        from_address=from_address,
        to_addresses=to_addresses,
        use_tls=parse_bool(os.getenv("SCRIVENER_ALERT_SMTP_USE_TLS"), default=True),
        subject_prefix=os.getenv("SCRIVENER_ALERT_SUBJECT_PREFIX", "[Scrivener Alert]").strip()
        or "[Scrivener Alert]",
    )


def load_state(state_file: Path) -> dict[str, dict[str, str]]:
    if not state_file.exists():
        return {"active_issues": {}}
    try:
        payload = json.loads(state_file.read_text())
    except json.JSONDecodeError:
        return {"active_issues": {}}
    active_issues = payload.get("active_issues")
    if not isinstance(active_issues, dict):
        return {"active_issues": {}}
    return {"active_issues": active_issues}


def save_state(state_file: Path, state: dict[str, dict[str, str]]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True))


def run_command(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def get_container_id(service: str, *, compose_dir: Path) -> str | None:
    output = run_command(["docker", "compose", "ps", "-q", service], cwd=compose_dir)
    return output.splitlines()[0] if output else None


def inspect_container(container_id: str, *, compose_dir: Path) -> dict[str, Any]:
    output = run_command(["docker", "inspect", container_id], cwd=compose_dir)
    payload = json.loads(output)
    if not payload:
        raise RuntimeError(f"No inspect payload for container {container_id}")
    return payload[0]


def tail_logs(container_id: str, *, compose_dir: Path, lines: int) -> str:
    result = subprocess.run(
        ["docker", "logs", "--tail", str(lines), container_id],
        cwd=str(compose_dir),
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip()
    if result.stderr.strip():
        stderr = result.stderr.strip()
        output = f"{output}\n{stderr}".strip()
    return output


def assess_service(
    service: str,
    inspect_payload: dict[str, Any] | None,
    *,
    logs: str = "",
) -> ServiceIssue | None:
    if inspect_payload is None:
        return ServiceIssue(
            service=service,
            fingerprint="missing-container",
            summary=f"Service '{service}' has no container",
            details={},
            logs=logs,
        )

    state = inspect_payload.get("State", {})
    status = state.get("Status", "unknown")
    restart_count = inspect_payload.get("RestartCount", 0)
    exit_code = state.get("ExitCode")
    health = state.get("Health", {})
    health_status = health.get("Status")

    details = {
        "status": status,
        "restart_count": restart_count,
        "exit_code": exit_code,
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "health_status": health_status,
    }

    if status != "running":
        fingerprint = f"status:{status}|exit:{exit_code}|restart:{restart_count}"
        return ServiceIssue(
            service=service,
            fingerprint=fingerprint,
            summary=f"Service '{service}' is {status}",
            details=details,
            logs=logs,
        )

    if health_status == "unhealthy":
        fingerprint = f"health:unhealthy|restart:{restart_count}"
        return ServiceIssue(
            service=service,
            fingerprint=fingerprint,
            summary=f"Service '{service}' is unhealthy",
            details=details,
            logs=logs,
        )

    return None


def should_send_alert(
    existing: AlertState | None,
    issue: ServiceIssue,
    *,
    current_time: datetime,
    cooldown: timedelta,
) -> bool:
    if existing is None:
        return True
    if existing.fingerprint != issue.fingerprint:
        return True
    last_alerted_at = datetime.fromisoformat(existing.last_alerted_at)
    return current_time - last_alerted_at >= cooldown


def send_email(config: EmailConfig, *, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = config.from_address
    message["To"] = ", ".join(config.to_addresses)
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(config.host, config.port, timeout=30) as server:
        if config.use_tls:
            server.starttls()
        if config.username and config.password:
            server.login(config.username, config.password)
        server.send_message(message)


def format_issue_body(issue: ServiceIssue, *, compose_dir: Path) -> str:
    lines = [
        f"Scrivener service issue detected at {now_utc().isoformat()}",
        "",
        f"Compose directory: {compose_dir}",
        f"Service: {issue.service}",
        f"Summary: {issue.summary}",
        f"Fingerprint: {issue.fingerprint}",
        "",
        "Details:",
    ]
    for key, value in issue.details.items():
        lines.append(f"- {key}: {value}")
    if issue.logs:
        lines.extend(["", "Recent logs:", issue.logs])
    return "\n".join(lines)


def format_recovery_body(service: str, *, compose_dir: Path) -> str:
    return "\n".join(
        [
            f"Scrivener service recovery detected at {now_utc().isoformat()}",
            "",
            f"Compose directory: {compose_dir}",
            f"Service: {service}",
            "Status: healthy/running",
        ]
    )


def monitor_services() -> int:
    compose_dir = Path(os.getenv("SCRIVENER_COMPOSE_DIR", os.getcwd())).resolve()
    state_file = Path(
        os.getenv(
            "SCRIVENER_ALERT_STATE_FILE",
            compose_dir / ".scrivener-watchdog-state.json",
        )
    )
    services = tuple(parse_csv(os.getenv("SCRIVENER_ALERT_SERVICES"))) or DEFAULT_SERVICES
    log_lines = int(os.getenv("SCRIVENER_ALERT_LOG_LINES", str(DEFAULT_LOG_LINES)))
    cooldown = timedelta(
        minutes=int(os.getenv("SCRIVENER_ALERT_COOLDOWN_MINUTES", str(DEFAULT_COOLDOWN_MINUTES)))
    )
    email_config = load_email_config()

    state = load_state(state_file)
    active_issues = dict(state["active_issues"])
    current_time = now_utc()

    for service in services:
        container_id = get_container_id(service, compose_dir=compose_dir)
        inspect_payload = (
            inspect_container(container_id, compose_dir=compose_dir) if container_id else None
        )
        logs = tail_logs(container_id, compose_dir=compose_dir, lines=log_lines) if container_id else ""
        issue = assess_service(service, inspect_payload, logs=logs)
        existing_payload = active_issues.get(service)
        existing = AlertState(**existing_payload) if existing_payload else None

        if issue is None:
            if existing is not None and email_config is not None:
                send_email(
                    email_config,
                    subject=f"{email_config.subject_prefix} Recovery: {service}",
                    body=format_recovery_body(service, compose_dir=compose_dir),
                )
            active_issues.pop(service, None)
            continue

        if email_config is not None and should_send_alert(
            existing,
            issue,
            current_time=current_time,
            cooldown=cooldown,
        ):
            send_email(
                email_config,
                subject=f"{email_config.subject_prefix} {issue.summary}",
                body=format_issue_body(issue, compose_dir=compose_dir),
            )
            active_issues[service] = asdict(
                AlertState(
                    fingerprint=issue.fingerprint,
                    last_alerted_at=current_time.isoformat(),
                )
            )
        elif existing is None:
            active_issues[service] = asdict(
                AlertState(
                    fingerprint=issue.fingerprint,
                    last_alerted_at=current_time.isoformat(),
                )
            )

    save_state(state_file, {"active_issues": active_issues})
    return 0


def main() -> int:
    try:
        return monitor_services()
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout or str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
