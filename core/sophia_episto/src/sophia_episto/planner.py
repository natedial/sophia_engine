"""Planner interfaces and a simple playbook-driven planner."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sophia_episto.plan_models import QuestionBrief, ResearchPlan
from sophia_episto.playbooks.base import Playbook


class PlannerStrategy(ABC):
    """Maps a question brief to a research plan."""

    @abstractmethod
    def build_plan(self, brief: QuestionBrief) -> ResearchPlan: ...


class PlaybookPlanner(PlannerStrategy):
    """Select the strongest matching playbook and draft a plan."""

    def __init__(self, playbooks: list[Playbook]) -> None:
        self.playbooks = playbooks

    def build_plan(self, brief: QuestionBrief) -> ResearchPlan:
        if not self.playbooks:
            raise ValueError("no playbooks registered")
        ranked = sorted(
            self.playbooks,
            key=lambda playbook: playbook.match(brief),
            reverse=True,
        )
        best = ranked[0]
        return best.draft_plan(brief)
