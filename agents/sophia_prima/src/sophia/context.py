"""Conversation context management with generic Message types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sophia.llm.types import Message, Role, ToolCall, ToolResultMessage


@dataclass
class ConversationContext:
    """Manages conversation state using provider-agnostic Message objects."""

    session_id: str
    messages: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation history."""
        self.messages.append(Message(role=Role.USER, content=content))

    def add_assistant_message(self, message: Message) -> None:
        """Add a full assistant Message (may include tool calls)."""
        self.messages.append(message)

    def add_tool_results(self, results: list[ToolResultMessage]) -> None:
        """Add tool results as a single user message."""
        self.messages.append(
            Message(role=Role.USER, tool_results=results)
        )


# ---------------------------------------------------------------------------
# Context transformation pipeline
# ---------------------------------------------------------------------------

ContextTransformer = Callable[[list[Message]], list[Message]]


def apply_transforms(
    messages: list[Message],
    transformers: list[ContextTransformer],
) -> list[Message]:
    """Apply a chain of transformers to a message list (non-mutating)."""
    result = list(messages)
    for transform in transformers:
        result = transform(result)
    return result


def truncate_to_token_budget(budget: int) -> ContextTransformer:
    """Keep only the most recent messages that fit within a rough token budget.

    Uses a simple heuristic: ~4 chars per token.
    Always preserves the first message (system context) and the last message.
    """

    def _transform(messages: list[Message]) -> list[Message]:
        if not messages:
            return messages

        total = 0
        keep: list[int] = []

        # Always keep last message, walk backwards
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            chars = len(msg.content)
            for tc in msg.tool_calls:
                chars += len(str(tc.input))
            for tr in msg.tool_results:
                chars += len(tr.content)

            estimated_tokens = chars // 4
            if total + estimated_tokens > budget and keep:
                break
            total += estimated_tokens
            keep.append(i)

        keep.reverse()

        # Always include the first message if it was dropped
        if keep and keep[0] != 0:
            keep.insert(0, 0)

        return [messages[i] for i in keep]

    return _transform


def summarize_long_tool_results(max_chars: int = 8000) -> ContextTransformer:
    """Truncate tool result content that exceeds max_chars."""

    def _transform(messages: list[Message]) -> list[Message]:
        out: list[Message] = []
        for msg in messages:
            if not msg.tool_results:
                out.append(msg)
                continue

            new_results: list[ToolResultMessage] = []
            for tr in msg.tool_results:
                if len(tr.content) > max_chars:
                    truncated = tr.content[:max_chars] + "\n... [truncated]"
                    new_results.append(
                        ToolResultMessage(
                            tool_call_id=tr.tool_call_id,
                            content=truncated,
                            is_error=tr.is_error,
                        )
                    )
                else:
                    new_results.append(tr)

            out.append(
                Message(
                    role=msg.role,
                    content=msg.content,
                    tool_calls=msg.tool_calls,
                    tool_results=new_results,
                    _raw=msg._raw,
                )
            )
        return out

    return _transform
