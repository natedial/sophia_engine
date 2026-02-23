"""Skill registry with lazy loading and matching."""

from __future__ import annotations

import logging
from pathlib import Path

from sophia.security.filesystem import ReadPolicy
from sophia.skills.loader import discover_skill_files, load_skill
from sophia.skills.matcher import select_best_skill
from sophia.skills.models import SkillManifest, SkillMatch

logger = logging.getLogger("sophia.skills")


class SkillRegistry:
    """Discovers and selects local skills."""

    def __init__(
        self,
        *,
        skills_root: Path,
        enabled: bool,
        max_loaded_chars: int,
        implicit_min_overlap: int,
        read_policy: ReadPolicy | None = None,
    ) -> None:
        self.skills_root = skills_root
        self.enabled = enabled
        self.max_loaded_chars = max_loaded_chars
        self.implicit_min_overlap = implicit_min_overlap
        self.read_policy = read_policy
        self._skills: list[SkillManifest] = []
        self._loaded = False

    def list_skills(self) -> list[SkillManifest]:
        """Return loaded skills (refreshing once lazily)."""
        if not self._loaded:
            self.refresh()
        return self._skills

    def refresh(self) -> None:
        """Reload skills from disk."""
        if self.read_policy is not None:
            self.read_policy.ensure_allowed(self.skills_root, purpose="skills_root")
        manifests: list[SkillManifest] = []
        for skill_file in discover_skill_files(self.skills_root):
            try:
                manifests.append(
                    load_skill(
                        skill_file,
                        max_body_chars=self.max_loaded_chars,
                        read_policy=self.read_policy,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to load skill %s: %s", skill_file, exc)
        self._skills = manifests
        self._loaded = True
        logger.info("Loaded %s skill(s) from %s", len(self._skills), self.skills_root)

    def match(self, user_message: str) -> SkillMatch | None:
        """Select at most one best-matching skill for the message."""
        if not self.enabled:
            return None
        return select_best_skill(
            user_message=user_message,
            skills=self.list_skills(),
            min_overlap=self.implicit_min_overlap,
        )
