"""Core Sophia agent - dual-loop architecture with event streaming."""

from __future__ import annotations

import logging
import re
import uuid
from typing import AsyncGenerator, Callable

from pylon import ErrorType, PreflightResult, Pylon, ToolResult

from sophia.config import Settings, get_settings
from sophia.context import ConversationContext, apply_transforms, summarize_long_tool_results
from sophia.events import (
    AgentEvent,
    agent_end,
    agent_start,
    message_delta,
    message_end,
    message_start,
    skill_activated,
    subagent_end,
    subagent_error,
    subagent_start,
    tool_execution_end,
    tool_execution_start,
    turn_end,
    turn_start,
)
from sophia.llm.base import ContentDelta, ModelProvider, StreamComplete
from sophia.llm.types import (
    CompletionResponse,
    Message,
    Role,
    ToolCall,
    ToolResultMessage,
    ToolSchema,
)
from sophia.memory import MemoryManager, MemoryManagerConfig, create_memory_store
from sophia.personality.loader import Personality, load_personality
from sophia.skills.models import SkillMatch
from sophia.skills.registry import SkillRegistry
from sophia.subagents import SubagentOrchestrator, SubagentProfile, SubagentResult, SubagentTask

# Type aliases for steering / follow-up callbacks
SteeringCallback = Callable[[], list[Message] | None]
FollowUpCallback = Callable[[], str | None]
logger = logging.getLogger("sophia.agent")


def _parse_lessons_markdown(raw: str) -> list[str]:
    """Parse markdown list/plain lines into lesson strings."""
    lessons: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        normalized = re.sub(r"^[-*]\s+", "", stripped)
        normalized = re.sub(r"^\d+\.\s+", "", normalized)
        normalized = normalized.strip()
        if not normalized:
            continue
        lessons.append(normalized)
    return lessons


class AgentConfig:
    """Tunables for the agent loop."""

    def __init__(
        self,
        *,
        max_tool_iterations: int = 10,
        stream: bool = True,
        context_transformers: list | None = None,
    ) -> None:
        self.max_tool_iterations = max_tool_iterations
        self.stream = stream
        self.context_transformers = context_transformers or [
            summarize_long_tool_results(),
        ]


class SophiaAgent:
    """
    Core Sophia agent with a dual-loop, event-streaming architecture.

    Outer loop: follow-up messages (multi-turn steering).
    Inner loop: tool calls + LLM round-trips.

    The provider is injected — this class never imports the Anthropic SDK.
    """

    def __init__(
        self,
        provider: ModelProvider,
        settings: Settings | None = None,
        pylon: Pylon | None = None,
        preflight_result: PreflightResult | None = None,
        agent_config: AgentConfig | None = None,
        memory_manager: MemoryManager | None = None,
        get_steering_messages: SteeringCallback | None = None,
        get_follow_up_messages: FollowUpCallback | None = None,
        canvas_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings or get_settings()
        self.read_policy = self.settings.build_read_policy()
        self.write_policy = self.settings.build_write_policy()
        self.seed_lessons = self._load_lessons()
        self.pylon = pylon or Pylon()
        self.preflight_result = preflight_result
        self.config = agent_config or AgentConfig()
        self.canvas_id = canvas_id
        if memory_manager is not None:
            self.memory = memory_manager
            self.memory.set_seed_lessons(self.seed_lessons)
        else:
            if self.settings.memory_store_backend.lower().strip() == "sqlite":
                self.read_policy.ensure_allowed(
                    self.settings.memory_store_path,
                    purpose="memory_store_path",
                )
                self.write_policy.ensure_allowed(
                    self.settings.memory_store_path,
                    purpose="memory_store_path",
                )
            memory_store = create_memory_store(
                backend=self.settings.memory_store_backend,
                sqlite_path=self.settings.memory_store_path,
                semantic_search_enabled=self.settings.memory_semantic_search_enabled,
                lexical_weight=self.settings.memory_lexical_weight,
                semantic_weight=self.settings.memory_semantic_weight,
                embedding_provider=self.settings.memory_embedding_provider,
                embedding_enabled=self.settings.memory_embedding_enabled,
                embedding_model=self.settings.memory_embedding_model,
                embed_episodic=self.settings.memory_embed_episodic,
                embed_semantic=self.settings.memory_embed_semantic,
                query_use_embedding_index=self.settings.memory_query_use_embedding_index,
                embedding_openai_api_key=(
                    self.settings.memory_embedding_openai_api_key
                    or self.settings.openai_api_key
                ),
                embedding_openai_base_url=self.settings.memory_embedding_openai_base_url,
                embedding_timeout_sec=self.settings.memory_embedding_timeout_sec,
                embedding_retry_max_attempts=self.settings.memory_embedding_retry_max_attempts,
                embedding_retry_base_delay_sec=(
                    self.settings.memory_embedding_retry_base_ms / 1000.0
                ),
                embedding_retry_max_delay_sec=(
                    self.settings.memory_embedding_retry_max_ms / 1000.0
                ),
                embedding_retry_jitter=self.settings.memory_embedding_retry_jitter,
            )
            self.memory = MemoryManager(
                store=memory_store,
                config=MemoryManagerConfig(
                    enabled=self.settings.memory_enabled,
                    working_window=self.settings.memory_working_window,
                    lessons_recall_k=self.settings.memory_lessons_top_k,
                    episodic_recall_k=self.settings.memory_episodic_top_k,
                    semantic_recall_k=self.settings.memory_semantic_top_k,
                    lesson_promotion_min_repeats=(
                        self.settings.memory_lesson_promotion_min_repeats
                    ),
                    compaction_enabled=self.settings.memory_compaction_enabled,
                    compaction_every_n_turns=self.settings.memory_compaction_every_n_turns,
                    compaction_max_episodic_per_session=(
                        self.settings.memory_compaction_max_episodic_per_session
                    ),
                    compaction_batch_size=self.settings.memory_compaction_batch_size,
                ),
                seed_lessons=self.seed_lessons,
            )
        self.get_steering_messages = get_steering_messages
        self.get_follow_up_messages = get_follow_up_messages
        self.personality = self._load_personality()
        self.soul = self._load_soul()
        self.skills = SkillRegistry(
            skills_root=self.settings.skills_path,
            enabled=self.settings.skills_enabled,
            max_loaded_chars=self.settings.skills_max_loaded_chars,
            implicit_min_overlap=self.settings.skills_implicit_match_min_overlap,
            read_policy=self.read_policy,
        )
        self.subagent_profiles = self._build_subagent_profiles()
        self.subagents = SubagentOrchestrator(
            profiles=self.subagent_profiles,
            max_parallel_workers=self.settings.subagents_max_parallel_workers,
        )

    def _build_subagent_profiles(self) -> dict[str, SubagentProfile]:
        default_timeout = self.settings.subagents_default_timeout_sec
        default_iters = self.settings.subagents_default_max_tool_iterations
        default_budget = self.settings.subagents_default_token_budget_chars
        default_result_chars = self.settings.subagents_default_max_result_chars

        return {
            "research_worker": SubagentProfile(
                name="research_worker",
                instructions=(
                    "You are a delegated research worker. Use tools to gather evidence, "
                    "then return concise factual findings with key values and dates."
                ),
                allowed_tools=None,
                max_tool_iterations=default_iters,
                timeout_sec=default_timeout,
                token_budget_chars=default_budget,
                max_result_chars=default_result_chars,
            ),
            "chart_worker": SubagentProfile(
                name="chart_worker",
                instructions=(
                    "You are a delegated chart worker. Use canvas creation tools to create "
                    "a chart relevant to the request, then report what was created."
                ),
                allowed_tools={
                    "create_timeseries_chart",
                    "create_comparison_chart",
                    "create_scatter_chart",
                    "create_yield_curve_chart",
                },
                max_tool_iterations=default_iters,
                timeout_sec=default_timeout,
                token_budget_chars=default_budget,
                max_result_chars=default_result_chars,
            ),
        }

    # ------------------------------------------------------------------
    # Personality
    # ------------------------------------------------------------------

    def _load_personality(self) -> Personality:
        self.read_policy.ensure_allowed(
            self.settings.personality_path,
            purpose="personality_path",
        )
        return load_personality(self.settings.personality_path)

    def _load_soul(self) -> str:
        soul_path = self.settings.soul_path
        self.read_policy.ensure_allowed(
            soul_path,
            purpose="soul_path",
        )
        if not soul_path.exists():
            logger.warning("Soul file not found: %s", soul_path)
            return ""
        return soul_path.read_text(encoding="utf-8").strip()

    def _load_lessons(self) -> list[str]:
        lessons_path = self.settings.lessons_path
        if not lessons_path.exists():
            return []

        self.read_policy.ensure_allowed(
            lessons_path,
            purpose="lessons_path",
        )
        raw = lessons_path.read_text(encoding="utf-8")
        return _parse_lessons_markdown(raw)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        context: ConversationContext | None = None,
        memory_context: str | None = None,
        active_skill: SkillMatch | None = None,
        active_tools: list[ToolSchema] | None = None,
        subagent_context: str | None = None,
    ) -> str:
        dynamic_context: dict[str, str] = {}

        if active_tools:
            tool_names = [t.name for t in active_tools]
            dynamic_context["Available tools"] = ", ".join(tool_names)
            dynamic_context["Tool use policy"] = (
                "When a user asks for data or computations and tools are available, "
                "you must call the appropriate tool(s) before answering. "
                "Do not fabricate numbers. If tools are unavailable, explain the limitation."
            )

        if self.preflight_result:
            service_status = self.preflight_result.for_system_prompt()
            if service_status:
                dynamic_context["Service status"] = service_status

        if self.canvas_id:
            dynamic_context["Active canvas"] = (
                f"Canvas ID: {self.canvas_id}\n"
                "Always use this canvas_id when calling visualization tools. "
                "Do not ask the user for a canvas ID."
            )

        if memory_context:
            dynamic_context["Memory context"] = memory_context

        if subagent_context:
            dynamic_context["Subagent findings"] = subagent_context

        if active_skill is not None:
            active_lines = [f"Name: {active_skill.skill.name}"]
            if active_skill.skill.description:
                active_lines.append(f"Description: {active_skill.skill.description}")
            active_lines.append(
                f"Match: {active_skill.reason} (score={active_skill.score:.2f})"
            )
            if active_skill.skill.allowed_tools is not None:
                if active_skill.skill.allowed_tools:
                    active_lines.append(
                        "Tool allowlist: " + ", ".join(active_skill.skill.allowed_tools)
                    )
                else:
                    active_lines.append("Tool allowlist: (none)")
            if active_skill.skill.read_allowlist:
                active_lines.append(
                    "Read scope: " + ", ".join(active_skill.skill.read_allowlist)
                )
            if active_skill.skill.write_allowlist:
                active_lines.append(
                    "Write scope: " + ", ".join(active_skill.skill.write_allowlist)
                )
            active_lines.append("Instructions:")
            active_lines.append(active_skill.skill.body)
            dynamic_context["Active skill"] = "\n".join(active_lines)

        system_prompt = self.personality.to_system_prompt(dynamic_context)
        if self.soul:
            system_prompt = f"{system_prompt}\n\n{self.soul}"
        return system_prompt

    @staticmethod
    def _build_enforced_tool_prompt(system_prompt: str) -> str:
        enforcement = (
            "\n\n## Tool Use Requirement\n"
            "If tools are available and the user asks for data or computations, "
            "you must call the appropriate tool(s) before answering. "
            "Do not answer from memory."
        )
        return f"{system_prompt}{enforcement}"

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    def _get_tool_schemas(self) -> list[ToolSchema]:
        """Get provider-agnostic tool schemas from pylon."""
        only_healthy = self.preflight_result is not None
        tool_defs = self.pylon.get_tools(only_healthy=only_healthy)
        return [
            ToolSchema(
                name=td.name,
                description=td.description,
                input_schema=td.to_generic_schema()["input_schema"],
            )
            for td in tool_defs
        ]

    @staticmethod
    def _should_enforce_tools(user_message: str, tools: list[ToolSchema]) -> bool:
        if not tools:
            return False

        message = user_message.lower()
        keywords = (
            "latest", "current", "value", "series", "observations", "data",
            "yield", "rate", "cpi", "gdp", "inflation", "unemployment",
            "treasury", "auction", "fed", "speech", "release",
            "compute", "regression", "mean", "median", "std",
            "percent change", "yoy", "mom", "moving average",
            "normalize", "log", "difference",
        )
        return any(kw in message for kw in keywords)

    @staticmethod
    def _latest_user_text(context: ConversationContext) -> str:
        for msg in reversed(context.messages):
            if msg.role == Role.USER and msg.content:
                return msg.content
        return ""

    async def _execute_tool(self, tool_call: ToolCall, allowed: set[str]) -> ToolResult:
        if tool_call.name not in allowed:
            return ToolResult.fail(f"Unknown tool: {tool_call.name}", ErrorType.INVALID_INPUT)
        return await self.pylon.execute_tool(tool_call.name, tool_call.input)

    @staticmethod
    def _scope_tools_for_skill(
        tools: list[ToolSchema],
        active_skill: SkillMatch | None,
    ) -> list[ToolSchema]:
        if active_skill is None or active_skill.skill.allowed_tools is None:
            return tools

        allowed = set(active_skill.skill.allowed_tools)
        return [tool for tool in tools if tool.name in allowed]

    @staticmethod
    def _scope_tools_for_profile(
        tools: list[ToolSchema],
        profile: SubagentProfile,
    ) -> list[ToolSchema]:
        if profile.allowed_tools is None:
            return tools
        return [tool for tool in tools if tool.name in profile.allowed_tools]

    def _should_delegate_subagents(
        self,
        message: str,
        available_tools: list[ToolSchema],
    ) -> bool:
        if not self.settings.subagents_enabled:
            return False
        planned = self.subagents.plan_for_message(
            message=message,
            available_tools=available_tools,
            canvas_id=self.canvas_id,
        )
        return bool(planned)

    @staticmethod
    def _format_subagent_summary(result: SubagentResult) -> str:
        if result.success:
            summary = result.content.strip()
            if summary:
                return f"[{result.profile_name}] {summary}"
            return f"[{result.profile_name}] completed"
        error = result.error or "Unknown subagent failure"
        return f"[{result.profile_name}] ERROR: {error}"

    def _build_subagent_context(self, results: list[SubagentResult]) -> str:
        lines = ["Delegated subagent outputs:"]
        for res in results:
            lines.append(f"- {self._format_subagent_summary(res)}")
        lines.append("Use these findings as additional context and validate where needed.")
        return "\n".join(lines)

    async def _run_subagent_task(
        self,
        task: SubagentTask,
        profile: SubagentProfile,
        parent_run_id: str,
    ) -> SubagentResult:
        sub_run_id = f"{parent_run_id}:{task.task_id}"
        context = ConversationContext(session_id=f"{task.task_id}:{sub_run_id}")
        context.add_user_message(task.prompt)

        available_tools = self._scope_tools_for_profile(self._get_tool_schemas(), profile)
        allowed_tool_names = {tool.name for tool in available_tools}
        worker_prompt = self._build_system_prompt(
            context=context,
            memory_context=None,
            active_skill=None,
            active_tools=available_tools,
        )
        worker_prompt = (
            f"{worker_prompt}\n\n"
            f"SUBAGENT PROFILE: {profile.name}\n"
            f"{profile.instructions}\n"
            "Return only execution findings for the supervisor. "
            "Do not address the user directly."
        )

        chars_used = 0
        iterations = 0
        last_message = ""

        while iterations < max(1, profile.max_tool_iterations):
            iterations += 1
            transformed = apply_transforms(context.messages, self.config.context_transformers)
            completion = await self.provider.complete(
                model=self.settings.llm_model,
                system=worker_prompt,
                messages=transformed,
                tools=available_tools or None,
            )

            assistant_msg = completion.message
            last_message = assistant_msg.content.strip()
            chars_used += len(assistant_msg.content)

            if chars_used > profile.token_budget_chars:
                return SubagentResult(
                    task_id=task.task_id,
                    profile_name=profile.name,
                    run_id=sub_run_id,
                    success=False,
                    error="Subagent token budget exceeded",
                    token_chars_used=chars_used,
                )

            context.add_assistant_message(assistant_msg)
            if not assistant_msg.tool_calls:
                content = last_message[: profile.max_result_chars]
                return SubagentResult(
                    task_id=task.task_id,
                    profile_name=profile.name,
                    run_id=sub_run_id,
                    success=True,
                    content=content,
                    token_chars_used=chars_used,
                )

            tool_results: list[ToolResultMessage] = []
            for tc in assistant_msg.tool_calls:
                result = await self._execute_tool(tc, allowed_tool_names)
                content = result.to_content()
                chars_used += len(content)
                if chars_used > profile.token_budget_chars:
                    return SubagentResult(
                        task_id=task.task_id,
                        profile_name=profile.name,
                        run_id=sub_run_id,
                        success=False,
                        error="Subagent token budget exceeded",
                        token_chars_used=chars_used,
                    )
                tool_results.append(
                    ToolResultMessage(
                        tool_call_id=tc.id,
                        content=content,
                        is_error=not result.success,
                    )
                )
            context.add_tool_results(tool_results)

        return SubagentResult(
            task_id=task.task_id,
            profile_name=profile.name,
            run_id=sub_run_id,
            success=False,
            error="Subagent max tool iterations reached",
            token_chars_used=chars_used,
        )

    # ------------------------------------------------------------------
    # Primary method — async generator of AgentEvents
    # ------------------------------------------------------------------

    async def run(
        self,
        message: str,
        context: ConversationContext,
        *,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        task_id: str | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        Process a user message, yielding AgentEvents as the agent works.

        This is the primary interface — callers iterate the generator and
        handle events (render text, show tool progress, etc.).
        """
        active_run_id = run_id or str(uuid.uuid4())
        yield agent_start(
            context.session_id,
            run_id=active_run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        )

        context.add_user_message(message)
        available_tools = self._get_tool_schemas()
        subagent_context: str | None = None
        if self._should_delegate_subagents(message, available_tools):
            tasks = self.subagents.plan_for_message(
                message=message,
                available_tools=available_tools,
                canvas_id=self.canvas_id,
            )
            child_run_ids: dict[str, str] = {}
            for delegated_task in tasks:
                profile_name = delegated_task.profile_name
                child_run_id = f"{active_run_id}:{delegated_task.task_id}"
                child_run_ids[delegated_task.task_id] = child_run_id
                yield subagent_start(
                    name=profile_name,
                    task=delegated_task.prompt,
                    run_id=child_run_id,
                    parent_run_id=active_run_id,
                    task_id=delegated_task.task_id,
                )

            results = await self.subagents.execute_plan(
                tasks=tasks,
                parent_run_id=active_run_id,
                run_worker=self._run_subagent_task,
            )
            for result in results:
                summary = self._format_subagent_summary(result)
                child_run_id = child_run_ids.get(
                    result.task_id,
                    f"{active_run_id}:{result.task_id}",
                )
                if result.success:
                    yield subagent_end(
                        name=result.profile_name,
                        summary=summary,
                        run_id=child_run_id,
                        parent_run_id=active_run_id,
                        task_id=result.task_id,
                    )
                else:
                    yield subagent_error(
                        name=result.profile_name,
                        error=result.error or "Unknown subagent failure",
                        timed_out=result.timed_out,
                        run_id=child_run_id,
                        parent_run_id=active_run_id,
                        task_id=result.task_id,
                    )
            if results:
                subagent_context = self._build_subagent_context(results)

        turn = 0

        # OUTER LOOP: follow-up messages
        while True:
            turn += 1
            yield turn_start(
                turn,
                run_id=active_run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
            )

            active_user_message = self._latest_user_text(context) or message
            active_skill = self.skills.match(active_user_message)
            if active_skill is not None:
                yield skill_activated(
                    name=active_skill.skill.name,
                    reason=active_skill.reason,
                    score=active_skill.score,
                    path=str(active_skill.skill.path),
                    run_id=active_run_id,
                    parent_run_id=parent_run_id,
                    task_id=task_id,
                )
            turn_tools = self._scope_tools_for_skill(available_tools, active_skill)
            allowed_tool_names = {tool.name for tool in turn_tools}
            memory_context = self.memory.recall_for_prompt(
                session_id=context.session_id,
                query=active_user_message,
                messages=context.messages,
            )
            system_prompt = self._build_system_prompt(
                context,
                memory_context,
                active_skill=active_skill,
                active_tools=turn_tools,
                subagent_context=subagent_context,
            )
            iterations = 0
            last_message: Message | None = None

            # INNER LOOP: tool calls
            while iterations < self.config.max_tool_iterations:
                iterations += 1

                # Check for steering messages
                if self.get_steering_messages:
                    steering = self.get_steering_messages()
                    if steering:
                        context.messages.extend(steering)

                # Apply context transforms
                transformed = apply_transforms(
                    context.messages, self.config.context_transformers
                )

                # Call provider
                yield message_start(
                    run_id=active_run_id,
                    parent_run_id=parent_run_id,
                    task_id=task_id,
                )

                if self.config.stream:
                    completion = None
                    async for event in self._stream_and_yield(
                        system_prompt,
                        transformed,
                        turn_tools,
                        run_id=active_run_id,
                        parent_run_id=parent_run_id,
                        task_id=task_id,
                    ):
                        if isinstance(event, AgentEvent):
                            yield event
                        else:
                            # It's the CompletionResponse
                            completion = event
                    assert completion is not None
                else:
                    completion = await self.provider.complete(
                        model=self.settings.llm_model,
                        system=system_prompt,
                        messages=transformed,
                        tools=turn_tools or None,
                    )

                assistant_msg = completion.message
                yield message_end(
                    assistant_msg,
                    run_id=active_run_id,
                    parent_run_id=parent_run_id,
                    task_id=task_id,
                )

                # Add assistant message to context
                context.add_assistant_message(assistant_msg)
                last_message = assistant_msg

                # If no tool calls, check enforcement then break
                if not assistant_msg.tool_calls:
                    # Tool enforcement check (first iteration only)
                    if iterations == 1 and self._should_enforce_tools(
                        active_user_message,
                        turn_tools,
                    ):
                        enforced_prompt = self._build_enforced_tool_prompt(system_prompt)
                        system_prompt = enforced_prompt
                        # Remove the assistant message we just added and retry
                        context.messages.pop()
                        continue

                    break

                # Execute tool calls
                tool_results: list[ToolResultMessage] = []
                for tc in assistant_msg.tool_calls:
                    yield tool_execution_start(
                        tc,
                        run_id=active_run_id,
                        parent_run_id=parent_run_id,
                        task_id=task_id,
                    )

                    result = await self._execute_tool(tc, allowed_tool_names)
                    content = result.to_content()
                    is_error = not result.success

                    yield tool_execution_end(
                        tc,
                        content,
                        is_error,
                        run_id=active_run_id,
                        parent_run_id=parent_run_id,
                        task_id=task_id,
                    )

                    tool_results.append(
                        ToolResultMessage(
                            tool_call_id=tc.id,
                            content=content,
                            is_error=is_error,
                        )
                    )

                    # Check steering between tool calls
                    if self.get_steering_messages:
                        steering = self.get_steering_messages()
                        if steering:
                            context.messages.extend(steering)
                            break  # Skip remaining tools, re-enter inner loop

                # Add tool results to context
                context.add_tool_results(tool_results)

            yield turn_end(
                turn,
                run_id=active_run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
            )

            if last_message is not None:
                self.memory.ingest_turn(
                    session_id=context.session_id,
                    user_message=active_user_message,
                    assistant_message=last_message.content,
                )

            # Check follow-up messages → continue outer loop or break
            if self.get_follow_up_messages:
                follow_up = self.get_follow_up_messages()
                if follow_up:
                    context.add_user_message(follow_up)
                    continue

            break

        yield agent_end(
            context.session_id,
            run_id=active_run_id,
            parent_run_id=parent_run_id,
            task_id=task_id,
        )

    # ------------------------------------------------------------------
    # Streaming helper
    # ------------------------------------------------------------------

    async def _stream_and_yield(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema],
        *,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        task_id: str | None = None,
    ) -> AsyncGenerator[AgentEvent | CompletionResponse, None]:
        """Stream from provider, yielding AgentEvents for deltas and the
        CompletionResponse as the final item."""
        async for event in self.provider.stream(
            model=self.settings.llm_model,
            system=system,
            messages=messages,
            tools=tools or None,
        ):
            if isinstance(event, ContentDelta):
                yield message_delta(
                    event.text,
                    run_id=run_id,
                    parent_run_id=parent_run_id,
                    task_id=task_id,
                )
            elif isinstance(event, StreamComplete):
                yield event.response

    # ------------------------------------------------------------------
    # Convenience method
    # ------------------------------------------------------------------

    async def chat(self, message: str, context: ConversationContext) -> Message:
        """Consume run() and return the final assistant message.

        This is a simpler interface for callers that don't need event streaming.
        """
        last_message: Message | None = None
        async for event in self.run(message, context):
            if event.type.value == "message_end":
                last_message = event.data["message"]

        if last_message is None:
            return Message(role=Role.ASSISTANT, content="No response generated.")

        return last_message
