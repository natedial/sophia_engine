"""Subagent planning and orchestration primitives."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
    metadata: dict[str, object] = field(default_factory=dict)


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
        wants_quant = any(
            token in lowered
            for token in (
                "compute",
                "calcula",
                "regression",
                "correl",
                "volatility",
                "mean",
                "median",
                "std",
                "percent change",
                "yoy",
                "mom",
            )
        )
        wants_citation_audit = any(
            token in lowered for token in ("citation", "citations", "source", "sources", "audit")
        )
        wants_memory = any(
            token in lowered for token in ("remember", "memory", "lesson", "preference")
        )
        wants_chart = any(
            token in lowered for token in ("chart", "plot", "visual", "dashboard", "canvas")
        )
        wants_scheduler = any(
            token in lowered for token in ("scheduler", "cron", "scheduled job", "task runner")
        )
        wants_data_pipeline = any(
            token in lowered
            for token in (
                "data pipe",
                "pipeline",
                "connector",
                "ingest",
                "ingestion",
                "fetcher",
                "source data",
                "etl",
            )
        )
        wants_engineering_action = any(
            token in lowered
            for token in (
                "build",
                "implement",
                "scaffold",
                "wire",
                "integrate",
                "add",
                "create",
                "set up",
                "setup",
                "plumb",
                "save",
                "commit",
                "patch",
                "deploy",
                "ship",
                "release",
            )
        )
        wants_tool_build = wants_engineering_action and _contains_any(
            lowered,
            (
                " tool",
                "tool ",
                "tools",
                "skill",
                "connector",
                "integration",
                "endpoint",
                "api",
                "command",
                "automation",
                "workflow",
                "bot",
            ),
        )
        wants_repo_mutation = (
            _contains_any(
                lowered,
                (
                    "save this to our codebase",
                    "save this to the codebase",
                    "save this to our repo",
                    "save this to the repo",
                    "write this into our codebase",
                    "write this into the codebase",
                    "write this into our repo",
                    "write this into the repo",
                    "write it into our codebase",
                    "write it into our repo",
                    "put it in our codebase",
                    "put it in the repo",
                    "build it in our codebase",
                    "build it in the repo",
                    "check it into the repo",
                    "open a pr",
                    "open the pr",
                    "pull request",
                    "commit this",
                    "commit it",
                    "apply the patch",
                    "apply this diff",
                ),
            )
            or (
                _contains_any(lowered, ("repo", "repository", "codebase", "branch"))
                and _contains_any(
                    lowered,
                    ("save", "write", "put", "add", "build", "implement", "commit", "patch"),
                )
            )
        )
        wants_deployment_work = _contains_any(
            lowered,
            (
                "deploy this",
                "deployment config",
                "deployment pipeline",
                "release this",
                "ship this",
                "roll this out",
                "roll it out",
            ),
        )
        if not any((wants_research, wants_quant, wants_citation_audit, wants_memory, wants_chart)):
            if not any(
                (
                    wants_scheduler,
                    wants_data_pipeline,
                    wants_engineering_action,
                    wants_tool_build,
                    wants_repo_mutation,
                    wants_deployment_work,
                )
            ):
                return []

        tool_names = {t.name for t in available_tools}
        has_data_tools = any(
            name.startswith("get_") or name.startswith("search_")
            for name in tool_names
        )
        has_compute_tools = "compute" in tool_names or "list_computation_types" in tool_names
        has_chart_tools = any(
            name.startswith("create_") and name.endswith("_chart")
            for name in tool_names
        )
        tasks: list[SubagentTask] = []
        should_delegate_coding = False
        coding_reasons: list[str] = []
        if wants_research and not has_data_tools:
            should_delegate_coding = True
            coding_reasons.append("data sourcing/retrieval capability is missing")
        if wants_quant and not has_compute_tools:
            should_delegate_coding = True
            coding_reasons.append("deterministic compute capability is missing")
        if wants_scheduler:
            should_delegate_coding = True
            coding_reasons.append("scheduler/task automation capability is requested")
        if wants_data_pipeline and wants_engineering_action:
            should_delegate_coding = True
            coding_reasons.append("data pipeline/integration work is requested")
        if wants_tool_build:
            should_delegate_coding = True
            coding_reasons.append("tooling/capability implementation is requested")
        if wants_repo_mutation:
            should_delegate_coding = True
            coding_reasons.append("explicit repo/codebase mutation is requested")
        if wants_deployment_work:
            should_delegate_coding = True
            coding_reasons.append("deployment workflow work is requested")
        if wants_research and has_data_tools:
            tasks.append(
                SubagentTask(
                    task_id="research",
                    profile_name="research_worker",
                    prompt=(
                        "Collect the strongest factual evidence for this request.\n"
                        f"User request: {message}"
                    ),
                )
            )
        if should_delegate_coding:
            reasons_text = (
                "; ".join(coding_reasons) if coding_reasons else "engineering work is requested"
            )
            tasks.append(
                SubagentTask(
                    task_id="coding",
                    profile_name="coding_worker",
                    prompt=(
                        "Inspect the repository and implement or scaffold the missing capability "
                        "needed for this request.\n"
                        f"Why delegated: {reasons_text}\n"
                        f"User request: {message}"
                    ),
                )
            )
        if wants_quant and has_compute_tools:
            tasks.append(
                SubagentTask(
                    task_id="quant",
                    profile_name="quant_worker",
                    prompt=(
                        "Run the smallest set of computations needed to support the request. "
                        "Return concrete outputs and any modeling caveats.\n"
                        f"User request: {message}"
                    ),
                )
            )
        if wants_chart and canvas_id and has_data_tools and has_chart_tools:
            tasks.append(
                SubagentTask(
                    task_id="chart",
                    profile_name="chart_worker",
                    prompt=(
                        f"Create one chart on canvas_id={canvas_id} that best supports this request.\n"
                        f"User request: {message}"
                    ),
                )
            )
        if wants_citation_audit and "search_research" in tool_names:
            tasks.append(
                SubagentTask(
                    task_id="citation_audit",
                    profile_name="citation_auditor",
                    prompt=(
                        "Identify the strongest evidence sources, the most likely citation gaps, "
                        "and any claims that require explicit sourcing.\n"
                        f"User request: {message}"
                    ),
                )
            )
        if wants_memory:
            tasks.append(
                SubagentTask(
                    task_id="memory",
                    profile_name="memory_curator",
                    prompt=(
                        "Extract the durable user preference, lesson, or project memory that "
                        "should survive this turn, and explain why.\n"
                        f"User request: {message}"
                    ),
                )
            )
        return tasks

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


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
