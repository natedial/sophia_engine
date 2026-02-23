"""Skill data models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillManifest:
    """Loaded skill metadata and instructions."""

    name: str
    description: str
    body: str
    path: Path
    allowed_tools: tuple[str, ...] | None = None
    read_allowlist: tuple[str, ...] = ()
    write_allowlist: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillMatch:
    """Selected skill for a user message."""

    skill: SkillManifest
    score: float
    reason: str
