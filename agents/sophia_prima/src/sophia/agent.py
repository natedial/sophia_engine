"""Core Sophia agent - dual-loop architecture with event streaming."""

from __future__ import annotations

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

# Type aliases for steering / follow-up callbacks
SteeringCallback = Callable[[], list[Message] | None]
FollowUpCallback = Callable[[], str | None]


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
        self.pylon = pylon or Pylon()
        self.preflight_result = preflight_result
        self.config = agent_config or AgentConfig()
        self.canvas_id = canvas_id
        if memory_manager is not None:
            self.memory = memory_manager
        else:
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
                    episodic_recall_k=self.settings.memory_episodic_top_k,
                    semantic_recall_k=self.settings.memory_semantic_top_k,
                    compaction_enabled=self.settings.memory_compaction_enabled,
                    compaction_every_n_turns=self.settings.memory_compaction_every_n_turns,
                    compaction_max_episodic_per_session=(
                        self.settings.memory_compaction_max_episodic_per_session
                    ),
                    compaction_batch_size=self.settings.memory_compaction_batch_size,
                ),
            )
        self.get_steering_messages = get_steering_messages
        self.get_follow_up_messages = get_follow_up_messages
        self.personality = self._load_personality()

    # ------------------------------------------------------------------
    # Personality
    # ------------------------------------------------------------------

    def _load_personality(self) -> Personality:
        return load_personality(self.settings.personality_path)

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        context: ConversationContext | None = None,
        memory_context: str | None = None,
    ) -> str:
        dynamic_context: dict[str, str] = {}

        only_healthy = self.preflight_result is not None
        tools = self.pylon.get_tools(only_healthy=only_healthy)
        if tools:
            tool_names = [t.name for t in tools]
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

        return self.personality.to_system_prompt(dynamic_context)

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

    # ------------------------------------------------------------------
    # Primary method — async generator of AgentEvents
    # ------------------------------------------------------------------

    async def run(
        self,
        message: str,
        context: ConversationContext,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        Process a user message, yielding AgentEvents as the agent works.

        This is the primary interface — callers iterate the generator and
        handle events (render text, show tool progress, etc.).
        """
        yield agent_start(context.session_id)

        context.add_user_message(message)
        tools = self._get_tool_schemas()
        allowed_tool_names = {t.name for t in tools}

        turn = 0

        # OUTER LOOP: follow-up messages
        while True:
            turn += 1
            yield turn_start(turn)

            active_user_message = self._latest_user_text(context) or message
            memory_context = self.memory.recall_for_prompt(
                session_id=context.session_id,
                query=active_user_message,
                messages=context.messages,
            )
            system_prompt = self._build_system_prompt(context, memory_context)
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
                yield message_start()

                if self.config.stream:
                    completion = None
                    async for event in self._stream_and_yield(
                        system_prompt, transformed, tools
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
                        tools=tools or None,
                    )

                assistant_msg = completion.message
                yield message_end(assistant_msg)

                # Add assistant message to context
                context.add_assistant_message(assistant_msg)
                last_message = assistant_msg

                # If no tool calls, check enforcement then break
                if not assistant_msg.tool_calls:
                    # Tool enforcement check (first iteration only)
                    if iterations == 1 and self._should_enforce_tools(message, tools):
                        enforced_prompt = self._build_enforced_tool_prompt(system_prompt)
                        system_prompt = enforced_prompt
                        # Remove the assistant message we just added and retry
                        context.messages.pop()
                        continue

                    break

                # Execute tool calls
                tool_results: list[ToolResultMessage] = []
                for tc in assistant_msg.tool_calls:
                    yield tool_execution_start(tc)

                    result = await self._execute_tool(tc, allowed_tool_names)
                    content = result.to_content()
                    is_error = not result.success

                    yield tool_execution_end(tc, content, is_error)

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

            yield turn_end(turn)

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

        yield agent_end(context.session_id)

    # ------------------------------------------------------------------
    # Streaming helper
    # ------------------------------------------------------------------

    async def _stream_and_yield(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSchema],
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
                yield message_delta(event.text)
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
