"""Typed profiles for specialized gateway agents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    """Behavioral and tool constraints for one top-level agent persona."""

    agent_id: str
    label: str
    description: str = ""
    prompt: str = ""
    tool_allowlist: tuple[str, ...] | None = None
    skills_enabled: bool | None = None
    subagents_enabled: bool | None = None
