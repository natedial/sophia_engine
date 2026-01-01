"""Core Sophia agent - orchestrates conversations with personality and tool use."""

from dataclasses import dataclass, field
from typing import Any

import anthropic
from pylon import ErrorType, PreflightResult, Pylon, ToolResult

from sophia.config import Settings, get_settings
from sophia.personality.loader import Personality, load_personality


@dataclass
class ConversationContext:
    """Context for an ongoing conversation."""

    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation history."""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str | list[dict[str, Any]]) -> None:
        """Add an assistant message (can be string or structured content)."""
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_result(self, tool_use_id: str, content: str) -> None:
        """Add a tool result message."""
        self.messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
        })

    def add_tool_results(self, results: list[tuple[str, str]]) -> None:
        """Add multiple tool results as a single message."""
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": content}
                for tool_id, content in results
            ],
        })

    def to_anthropic_messages(self) -> list[dict[str, Any]]:
        """Convert to Anthropic API message format."""
        return self.messages.copy()


@dataclass
class Response:
    """Agent response to a user message."""

    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


class SophiaAgent:
    """
    Core Sophia agent that orchestrates conversations.

    Handles:
    - Personality-driven system prompts
    - Tool discovery and execution via Pylon gateway
    - Conversation state management
    - Pre-flight checks and graceful degradation
    """

    def __init__(
        self,
        settings: Settings | None = None,
        pylon: Pylon | None = None,
        preflight_result: PreflightResult | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.pylon = pylon or Pylon()
        self.preflight_result = preflight_result
        self.personality = self._load_personality()
        self.client = self._create_client()

    def _load_personality(self) -> Personality:
        """Load the personality configuration."""
        return load_personality(self.settings.personality_path)

    def _create_client(self) -> anthropic.Anthropic:
        """Create the Anthropic API client."""
        return anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    def _build_system_prompt(self, context: ConversationContext | None = None) -> str:
        """Build the system prompt with personality and dynamic context."""
        dynamic_context = {}

        # Add available tools to context (only healthy ones if we have preflight data)
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

        # Inject service status if any services are degraded
        if self.preflight_result:
            service_status = self.preflight_result.for_system_prompt()
            if service_status:
                dynamic_context["Service status"] = service_status

        return self.personality.to_system_prompt(dynamic_context)

    async def chat(
        self,
        message: str,
        context: ConversationContext,
    ) -> Response:
        """
        Process a user message and generate a response.

        Args:
            message: User's input message
            context: Conversation context with history

        Returns:
            Agent response
        """
        # Add user message to context
        context.add_user_message(message)

        # Get available tools (only healthy ones if preflight was run)
        only_healthy = self.preflight_result is not None
        tools = self.pylon.get_tools_as_anthropic_schema(only_healthy=only_healthy)

        # Build request
        system_prompt = self._build_system_prompt(context)
        messages = context.to_anthropic_messages()

        # Call Anthropic API
        response = await self._call_llm(system_prompt, messages, tools)

        # Process response - handle tool calls if present
        final_response, raw_content = await self._process_response(
            response,
            context,
            tools,
            system_prompt,
            messages,
            message,
        )

        # Add assistant response to context (preserve structured content if tool use)
        context.add_assistant_message(raw_content)

        return final_response

    async def _call_llm(
        self,
        system: str,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> anthropic.types.Message:
        """Make an API call to the LLM."""
        kwargs: dict[str, Any] = {
            "model": self.settings.llm_model,
            "max_tokens": 4096,
            "system": system,
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools

        # Use sync client in async context (anthropic SDK handles this)
        return self.client.messages.create(**kwargs)

    async def _process_response(
        self,
        response: anthropic.types.Message,
        context: ConversationContext,
        tools: list[dict[str, Any]],
        system_prompt: str,
        messages: list[dict[str, Any]],
        user_message: str,
    ) -> tuple[Response, str | list[dict[str, Any]]]:
        """Process LLM response, handling tool calls if present.

        Returns:
            Tuple of (Response, raw_content_for_context)
        """
        tool_calls, text_content = self._extract_response_content(response)
        tool_results = []

        # Execute tool calls if any
        if tool_calls:
            tool_results = await self._execute_tools(tool_calls, tools)

            # Continue conversation with tool results
            return await self._continue_with_tool_results(
                context, tools, response, tool_calls, tool_results
            )

        if self._should_enforce_tools(user_message, tools):
            enforced_prompt = self._build_enforced_tool_prompt(system_prompt)
            enforced_response = await self._call_llm(enforced_prompt, messages, tools)
            enforced_tool_calls, enforced_text = self._extract_response_content(enforced_response)

            if enforced_tool_calls:
                enforced_results = await self._execute_tools(enforced_tool_calls, tools)
                return await self._continue_with_tool_results(
                    context, tools, enforced_response, enforced_tool_calls, enforced_results
                )

            refusal = (
                "I need to call the available tools to answer that accurately. "
                "Please confirm you're okay with tool use or rephrase the request."
            )
            return Response(content=refusal), refusal

        return Response(
            content=text_content,
            tool_calls=tool_calls,
            tool_results=tool_results,
        ), text_content

    async def _execute_tools(
        self,
        tool_calls: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> list[ToolResult]:
        """Execute a list of tool calls via Pylon."""
        allowed_tools = {tool["name"] for tool in tools}
        results = []
        for call in tool_calls:
            if call["name"] not in allowed_tools:
                results.append(
                    ToolResult.fail(
                        f"Unknown tool: {call['name']}",
                        ErrorType.INVALID_INPUT,
                    )
                )
                continue
            result = await self.pylon.execute_tool(call["name"], call["input"])
            results.append(result)
        return results

    async def _continue_with_tool_results(
        self,
        context: ConversationContext,
        tools: list[dict[str, Any]],
        original_response: anthropic.types.Message,
        tool_calls: list[dict[str, Any]],
        tool_results: list[ToolResult],
        max_iterations: int = 10,
    ) -> tuple[Response, str]:
        """Continue the conversation after tool execution, looping if more tools needed."""
        all_tool_calls = tool_calls.copy()
        all_tool_results = tool_results.copy()

        # Add assistant message with tool use to context
        assistant_content = [block.model_dump() for block in original_response.content]
        context.add_assistant_message(assistant_content)

        # Add tool results to context
        context.add_tool_results([
            (call["id"], result.to_content())
            for call, result in zip(tool_calls, tool_results)
        ])

        iteration = 0
        while iteration < max_iterations:
            iteration += 1

            # Get next response using updated context
            system_prompt = self._build_system_prompt(context)
            messages = context.to_anthropic_messages()
            response = await self._call_llm(system_prompt, messages, tools)

            # Check if more tool calls needed
            new_tool_calls = []
            text_content = ""

            for block in response.content:
                if block.type == "text":
                    text_content += block.text
                elif block.type == "tool_use":
                    new_tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            # If no more tool calls, we're done
            if not new_tool_calls:
                return Response(
                    content=text_content,
                    tool_calls=all_tool_calls,
                    tool_results=all_tool_results,
                ), text_content

            # Execute new tool calls
            new_results = await self._execute_tools(new_tool_calls, tools)
            all_tool_calls.extend(new_tool_calls)
            all_tool_results.extend(new_results)

            # Add to context and loop
            assistant_content = [block.model_dump() for block in response.content]
            context.add_assistant_message(assistant_content)
            context.add_tool_results([
                (call["id"], result.to_content())
                for call, result in zip(new_tool_calls, new_results)
            ])

        # Max iterations reached
        return Response(
            content="I'm having trouble completing this request. Please try again.",
            tool_calls=all_tool_calls,
            tool_results=all_tool_results,
        ), "Max tool iterations reached"

    @staticmethod
    def _extract_response_content(
        response: anthropic.types.Message,
    ) -> tuple[list[dict[str, Any]], str]:
        """Extract tool calls and text content from an LLM response."""
        tool_calls: list[dict[str, Any]] = []
        text_content = ""

        for block in response.content:
            if block.type == "text":
                text_content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        return tool_calls, text_content

    @staticmethod
    def _build_enforced_tool_prompt(system_prompt: str) -> str:
        """Append a hard tool-use requirement to the system prompt."""
        enforcement = (
            "\n\n## Tool Use Requirement\n"
            "If tools are available and the user asks for data or computations, "
            "you must call the appropriate tool(s) before answering. "
            "Do not answer from memory."
        )
        return f"{system_prompt}{enforcement}"

    @staticmethod
    def _should_enforce_tools(user_message: str, tools: list[dict[str, Any]]) -> bool:
        """Heuristic to decide when tool use must be enforced."""
        if not tools:
            return False

        message = user_message.lower()
        keywords = (
            "latest",
            "current",
            "value",
            "series",
            "observations",
            "data",
            "yield",
            "rate",
            "cpi",
            "gdp",
            "inflation",
            "unemployment",
            "treasury",
            "auction",
            "fed",
            "speech",
            "release",
            "compute",
            "regression",
            "mean",
            "median",
            "std",
            "percent change",
            "yoy",
            "mom",
            "moving average",
            "normalize",
            "log",
            "difference",
        )

        return any(keyword in message for keyword in keywords)
