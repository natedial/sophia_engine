"""Injectable clocks for lease expiry.

A file-backed clock lets separate processes share one timeline in tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current UTC instant."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FileClock:
    """Clock whose instant is stored in a file, shared across processes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.set(datetime.now(UTC))

    def now(self) -> datetime:
        text = self.path.read_text(encoding="utf-8").strip()
        instant = datetime.fromisoformat(text)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        return instant.astimezone(UTC)

    def set(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        else:
            instant = instant.astimezone(UTC)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(instant.isoformat(), encoding="utf-8")
        tmp.replace(self.path)

    def advance(self, seconds: float) -> datetime:
        nxt = self.now() + timedelta(seconds=seconds)
        self.set(nxt)
        return nxt
