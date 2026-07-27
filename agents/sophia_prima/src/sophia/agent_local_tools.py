"""Agent-local tools for memory curation.

These tools operate on agent-local state (memory store) rather than
external services (Pylon). They allow the agent to explicitly remember,
forget, or inspect its own memory.
"""

from __future__ import annotations

import logging
from typing import Any

from sophia.config import Settings, get_settings
from sophia.memory.manager import MemoryManager
from sophia.memory.safety import normalize_for_comparison, validate_memory_content
from sophia.memory.types import MemoryLevel
from sophia.security.filesystem import ReadPolicy, WritePolicy
from sophia.self_editing import SelfEditChangeRequest, build_self_edit_service

logger = logging.getLogger(__name__)


class AgentLocalTools:
    """Agent-local tool implementations for memory curation."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        *,
        settings: Settings | None = None,
        read_policy: ReadPolicy | None = None,
        write_policy: WritePolicy | None = None,
    ) -> None:
        self._memory = memory_manager
        self._settings = settings
        self._read_policy = read_policy
        self._write_policy = write_policy

    def remember(
        self,
        content: str,
        level: str = "semantic",
        tags: list[str] | None = None,
    ) -> str:
        """Save a durable fact, preference, or lesson to memory.

        Args:
            content: The memory to store.
            level: Memory level ("semantic" or "lessons").
            tags: Optional tags for the memory.

        Returns:
            Confirmation message with record count.
        """
        error = validate_memory_content(content)
        if error:
            return f"Error: {error}"

        valid_levels = {"semantic", "lessons"}
        if level not in valid_levels:
            return f"Error: Invalid level '{level}'. Must be one of: {', '.join(valid_levels)}"

        memory_level = MemoryLevel(level)
        record_tags = set(tags) if tags else set()

        from sophia.memory.types import MemoryRecord

        self._memory.store.add(
            MemoryRecord(
                level=memory_level,
                content=content,
                session_id=None,
                tags=record_tags,
                salience=0.7,
            )
        )

        return f"Remembered: {content[:100]}{'...' if len(content) > 100 else ''}"

    def forget(self, substring: str, level: str | None = None) -> str:
        """Remove a memory record by matching a unique substring.

        Args:
            substring: Text to search for in memory content.
            level: Optional memory level to restrict search to.

        Returns:
            Confirmation or error message.
        """
        if not substring or not substring.strip():
            return "Error: Substring cannot be empty."

        levels: set[MemoryLevel] | None = None
        if level:
            valid_levels = {"semantic", "lessons", "episodic", "working"}
            if level not in valid_levels:
                return f"Error: Invalid level '{level}'. Must be one of: {', '.join(valid_levels)}"
            levels = {MemoryLevel(level)}

        matches = self._memory.store.search_by_substring(
            substring=substring,
            levels=levels,
        )

        if not matches:
            return "No matching memory found."

        if len(matches) == 1:
            self._memory.store.delete_ids([matches[0].id])
            return f"Forgotten: {matches[0].content[:100]}{'...' if len(matches[0].content) > 100 else ''}"

        normalized_substring = normalize_for_comparison(substring)
        unique_matches = {normalize_for_comparison(m.content): m for m in matches}

        if len(unique_matches) == 1:
            match = list(unique_matches.values())[0]
            self._memory.store.delete_ids([match.id])
            return f"Forgotten: {match.content[:100]}{'...' if len(match.content) > 100 else ''}"

        match_list = "\n".join(
            f"- {m.content[:80]}{'...' if len(m.content) > 80 else ''}" for m in matches[:5]
        )
        return f"Multiple matches found. Please be more specific:\n{match_list}"

    def list_memory(
        self,
        level: str | None = None,
        limit: int = 10,
    ) -> str:
        """List current memory records.

        Args:
            level: Optional memory level to filter by.
            limit: Maximum number of records to return.

        Returns:
            Formatted list of memory records.
        """
        valid_levels = {"semantic", "lessons", "episodic", "working"}
        if level and level not in valid_levels:
            return f"Error: Invalid level '{level}'. Must be one of: {', '.join(valid_levels)}"

        levels: set[MemoryLevel] | None = None
        if level:
            levels = {MemoryLevel(level)}

        records = self._memory.store.list_records(
            session_id=None,
            levels=levels,
            limit=limit,
            newest_first=True,
        )

        if not records:
            return "No memory records found."

        lines = []
        for rec in records:
            created = rec.created_at.strftime("%Y-%m-%d %H:%M")
            tags_str = f" [{', '.join(sorted(rec.tags))}]" if rec.tags else ""
            lines.append(
                f"- [{rec.level.value}]{tags_str} @ {created}: {rec.content[:100]}"
                f"{'...' if len(rec.content) > 100 else ''}"
            )

        return "\n".join(lines)

    def propose_self_edit(
        self,
        title: str,
        rationale: str,
        changes: list[dict[str, Any]],
    ) -> str:
        """Create a reviewable self-edit proposal instead of editing repo files directly."""
        try:
            service = build_self_edit_service(
                settings=self._settings or get_settings(),
                read_policy=self._read_policy,
                write_policy=self._write_policy,
            )
            proposal = service.create_proposal(
                title=title,
                rationale=rationale,
                changes=[SelfEditChangeRequest.model_validate(item) for item in changes],
            )
        except Exception as exc:
            return f"Error: {exc}"

        return (
            "Created self-edit proposal "
            f"{proposal.proposal_id} with {len(proposal.changes)} file change(s). "
            f"Status={proposal.status}. Patch={proposal.patch_path}. "
            "Repo files were not modified; human approval is required before promotion."
        )


def create_local_tools(
    memory_manager: MemoryManager,
    *,
    settings: Settings | None = None,
    read_policy: ReadPolicy | None = None,
    write_policy: WritePolicy | None = None,
) -> dict[str, Any]:
    """Create the agent-local tool definitions.

    Returns a dict mapping tool names to their schemas and handlers.
    """
    tools = AgentLocalTools(
        memory_manager,
        settings=settings,
        read_policy=read_policy,
        write_policy=write_policy,
    )

    return {
        "remember": {
            "name": "remember",
            "description": "Save a durable fact, preference, or lesson to memory. "
            "Saved memories persist across sessions but take effect "
            "in the next session's memory snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The memory content to store.",
                    },
                    "level": {
                        "type": "string",
                        "enum": ["semantic", "lessons"],
                        "default": "semantic",
                        "description": "Memory level for the record.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for the memory.",
                    },
                },
                "required": ["content"],
            },
            "handler": tools.remember,
        },
        "forget": {
            "name": "forget",
            "description": "Remove a memory record by matching a unique substring. "
            "Takes effect in the next session's memory snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "substring": {
                        "type": "string",
                        "description": "Text to search for in memory content.",
                    },
                    "level": {
                        "type": "string",
                        "enum": ["semantic", "lessons", "episodic", "working"],
                        "description": "Optional memory level to restrict search to.",
                    },
                },
                "required": ["substring"],
            },
            "handler": tools.forget,
        },
        "list_memory": {
            "name": "list_memory",
            "description": "List current memory records, optionally filtered by level.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["semantic", "lessons", "episodic", "working"],
                        "description": "Optional memory level to filter by.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum number of records to return.",
                    },
                },
            },
            "handler": tools.list_memory,
        },
        "propose_self_edit": {
            "name": "propose_self_edit",
            "description": (
                "Create a reviewable self-edit proposal for Sophia-owned config or skill files. "
                "This writes only proposal artifacts under .sophia and does not modify repo files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title for the proposed self-edit.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why Sophia should adopt this change.",
                    },
                    "changes": {
                        "type": "array",
                        "description": "One or more full-file replacements for allowed self-edit targets.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target_path": {
                                    "type": "string",
                                    "description": "Project-relative target file path.",
                                },
                                "updated_content": {
                                    "type": "string",
                                    "description": "Full replacement file contents.",
                                },
                                "summary": {
                                    "type": "string",
                                    "description": "Short summary of what changed in this file.",
                                },
                            },
                            "required": ["target_path", "updated_content"],
                        },
                    },
                },
                "required": ["title", "rationale", "changes"],
            },
            "handler": tools.propose_self_edit,
        },
    }
