"""Filesystem permission policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def parse_allowlist(raw: str, *, project_root: Path) -> tuple[Path, ...]:
    """Parse a comma-separated allowlist into normalized absolute paths."""
    items = [item.strip() for item in raw.split(",") if item.strip()]
    roots: list[Path] = []
    for item in items:
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = project_root / path
        roots.append(path.resolve(strict=False))
    return tuple(roots)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class WritePolicy:
    """Deny-by-default write policy enforced against an explicit allowlist."""

    enabled: bool
    allowed_roots: tuple[Path, ...]

    def is_allowed(self, path: Path) -> bool:
        if not self.enabled:
            return True
        target = path.expanduser().resolve(strict=False)
        return any(_is_within(target, root) for root in self.allowed_roots)

    def ensure_allowed(self, path: Path, *, purpose: str) -> None:
        if self.is_allowed(path):
            return

        roots = ", ".join(str(root) for root in self.allowed_roots) or "(none)"
        raise PermissionError(
            "Write denied by policy. "
            f"purpose={purpose}, path={path.expanduser().resolve(strict=False)}, "
            f"allowed_roots={roots}"
        )


@dataclass(frozen=True)
class ReadPolicy:
    """Deny-by-default read policy enforced against an explicit allowlist."""

    enabled: bool
    allowed_roots: tuple[Path, ...]

    def is_allowed(self, path: Path) -> bool:
        if not self.enabled:
            return True
        target = path.expanduser().resolve(strict=False)
        return any(_is_within(target, root) for root in self.allowed_roots)

    def ensure_allowed(self, path: Path, *, purpose: str) -> None:
        if self.is_allowed(path):
            return

        roots = ", ".join(str(root) for root in self.allowed_roots) or "(none)"
        raise PermissionError(
            "Read denied by policy. "
            f"purpose={purpose}, path={path.expanduser().resolve(strict=False)}, "
            f"allowed_roots={roots}"
        )
