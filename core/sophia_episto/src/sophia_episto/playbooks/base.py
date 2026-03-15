"""Playbook base interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sophia_episto.plan_models import QuestionBrief, ResearchPlan


class Playbook(ABC):
    playbook_id: str
    name: str
    description: str

    @abstractmethod
    def match(self, brief: QuestionBrief) -> float: ...

    @abstractmethod
    def draft_plan(self, brief: QuestionBrief) -> ResearchPlan: ...
