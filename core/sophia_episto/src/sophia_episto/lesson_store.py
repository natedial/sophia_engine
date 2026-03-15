"""Lesson provider interfaces for Episto."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sophia_episto.plan_models import LessonRecord, QuestionBrief


class LessonProvider(ABC):
    @abstractmethod
    def lookup(self, brief: QuestionBrief, *, tags: tuple[str, ...] = ()) -> list[LessonRecord]: ...


class InMemoryLessonStore(LessonProvider):
    def __init__(self, lessons: list[LessonRecord] | None = None) -> None:
        self.lessons = lessons or []

    def lookup(self, brief: QuestionBrief, *, tags: tuple[str, ...] = ()) -> list[LessonRecord]:
        required = set(tags) | set(brief.tags)
        if not required:
            return list(self.lessons)
        return [
            lesson
            for lesson in self.lessons
            if required.intersection(lesson.tags)
        ]
