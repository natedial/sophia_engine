"""Subagent planning and orchestration primitives."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from sophia.llm.types import ToolSchema


@dataclass(frozen=True)
class SubagentProfile:
    """Execution constraints and scope for one worker type."""

    name: str
    instructions: str
    allowed_tools: set[str] | None = None
    max_tool_iterations: int = 4
    timeout_sec: float = 20.0
    token_budget_chars: int = 24000
    max_result_chars: int = 4000


@dataclass(frozen=True)
class SubagentTask:
    """A single delegated task in a parent run."""

    task_id: str
    profile_name: str
    prompt: str


@dataclass(frozen=True)
class SubagentResult:
    """Outcome of one delegated task."""

    task_id: str
    profile_name: str
    run_id: str
    success: bool
    content: str = ""
    error: str | None = None
    timed_out: bool = False
    token_chars_used: int = 0


RunWorker = Callable[[SubagentTask, SubagentProfile, str], Awaitable[SubagentResult]]


class SubagentOrchestrator:
    """Runs delegated tasks with bounded parallelism."""

    def __init__(
        self,
        *,
        profiles: dict[str, SubagentProfile],
        max_parallel_workers: int,
    ) -> None:
        self._profiles = profiles
        self._max_parallel_workers = max(1, max_parallel_workers)

    @property
    def profiles(self) -> dict[str, SubagentProfile]:
        return self._profiles

    def get_profile(self, name: str) -> SubagentProfile | None:
        return self._profiles.get(name)

    def plan_for_message(
        self,
        *,
        message: str,
        available_tools: list[ToolSchema],
        canvas_id: str | None,
    ) -> list[SubagentTask]:
        """Create a deterministic task plan for the delegated thin-slice."""
        lowered = message.lower()
        wants_research = any(token in lowered for token in ("research", "analy", "brief"))
        wants_chart = any(
            token in lowered for token in ("chart", "plot", "visual", "dashboard", "canvas")
        )
        if not (wants_research and wants_chart and canvas_id):
            return []

        tool_names = {t.name for t in available_tools}
        has_data_tools = any(
            name.startswith("get_") or name.startswith("search_")
            for name in tool_names
        )
        has_chart_tools = any(
            name.startswith("create_") and name.endswith("_chart")
            for name in tool_names
        )
        if not has_data_tools or not has_chart_tools:
            return []

        return [
            SubagentTask(
                task_id="research",
                profile_name="research_worker",
                prompt=(
                    "Collect the strongest factual evidence for this request.\n"
                    f"User request: {message}"
                ),
            ),
            SubagentTask(
                task_id="chart",
                profile_name="chart_worker",
                prompt=(
                    f"Create one chart on canvas_id={canvas_id} that best supports this request.\n"
                    f"User request: {message}"
                ),
            ),
        ]

    async def execute_plan(
        self,
        *,
        tasks: list[SubagentTask],
        parent_run_id: str,
        run_worker: RunWorker,
    ) -> list[SubagentResult]:
        """Execute all tasks and return results in completion order."""
        semaphore = asyncio.Semaphore(self._max_parallel_workers)

        async def _run_task(task: SubagentTask, profile: SubagentProfile) -> SubagentResult:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        run_worker(task, profile, parent_run_id),
                        timeout=max(0.1, profile.timeout_sec),
                    )
                except TimeoutError:
                    return SubagentResult(
                        task_id=task.task_id,
                        profile_name=task.profile_name,
                        run_id=f"{parent_run_id}:{task.task_id}",
                        success=False,
                        error="Subagent timed out",
                        timed_out=True,
                    )
                except Exception as exc:
                    return SubagentResult(
                        task_id=task.task_id,
                        profile_name=task.profile_name,
                        run_id=f"{parent_run_id}:{task.task_id}",
                        success=False,
                        error=str(exc),
                        timed_out=False,
                    )

        futures: list[asyncio.Task[SubagentResult]] = []
        for task in tasks:
            profile = self.get_profile(task.profile_name)
            if profile is None:
                futures.append(
                    asyncio.create_task(
                        asyncio.sleep(
                            0,
                            result=SubagentResult(
                                task_id=task.task_id,
                                profile_name=task.profile_name,
                                run_id=f"{parent_run_id}:{task.task_id}",
                                success=False,
                                error=f"Unknown subagent profile: {task.profile_name}",
                            ),
                        )
                    )
                )
                continue
            futures.append(asyncio.create_task(_run_task(task, profile)))

        if not futures:
            return []

        results: list[SubagentResult] = []
        for fut in asyncio.as_completed(futures):
            results.append(await fut)
        return results
