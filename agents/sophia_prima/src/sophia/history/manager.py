"""High-level manager for append-only debugging history."""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import Any

from sophia.history.store import HistoryStore, SQLiteHistoryStore
from sophia.history.types import HistoryEventRecord, HistoryEventType
from sophia.llm.types import ToolCall

logger = logging.getLogger(__name__)


class LosslessHistoryManager:
    """Capture raw-ish turn and tool activity without affecting prompt memory."""

    def __init__(
        self,
        *,
        store: HistoryStore,
        tool_result_max_chars: int = 50000,
    ) -> None:
        self.store = store
        self.tool_result_max_chars = max(0, tool_result_max_chars)

    @classmethod
    def from_sqlite(
        cls,
        *,
        db_path,
        tool_result_max_chars: int = 50000,
    ) -> "LosslessHistoryManager":
        return cls(
            store=SQLiteHistoryStore(db_path),
            tool_result_max_chars=tool_result_max_chars,
        )

    def record_turn_input(
        self,
        *,
        session_id: str,
        run_id: str | None,
        parent_run_id: str | None,
        task_id: str | None,
        turn: int,
        user_message: str,
    ) -> None:
        self._append(
            HistoryEventRecord(
                session_id=session_id,
                run_id=run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
                turn=turn,
                event_type=HistoryEventType.TURN_INPUT,
                payload={"user_message": user_message},
            )
        )

    def record_turn_output(
        self,
        *,
        session_id: str,
        run_id: str | None,
        parent_run_id: str | None,
        task_id: str | None,
        turn: int,
        assistant_message: str,
        used_tools: bool,
    ) -> None:
        self._append(
            HistoryEventRecord(
                session_id=session_id,
                run_id=run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
                turn=turn,
                event_type=HistoryEventType.TURN_OUTPUT,
                payload={
                    "assistant_message": assistant_message,
                    "used_tools": used_tools,
                },
            )
        )

    def record_tool_start(
        self,
        *,
        session_id: str,
        run_id: str | None,
        parent_run_id: str | None,
        task_id: str | None,
        turn: int,
        tool_call: ToolCall,
    ) -> None:
        self._append(
            HistoryEventRecord(
                session_id=session_id,
                run_id=run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
                turn=turn,
                event_type=HistoryEventType.TOOL_START,
                payload={"tool_call": _serialize_tool_call(tool_call)},
            )
        )

    def record_tool_end(
        self,
        *,
        session_id: str,
        run_id: str | None,
        parent_run_id: str | None,
        task_id: str | None,
        turn: int,
        tool_call: ToolCall,
        result: str,
        is_error: bool,
    ) -> None:
        truncated_result = result
        was_truncated = False
        if self.tool_result_max_chars and len(result) > self.tool_result_max_chars:
            truncated_result = result[: self.tool_result_max_chars]
            was_truncated = True
        self._append(
            HistoryEventRecord(
                session_id=session_id,
                run_id=run_id,
                parent_run_id=parent_run_id,
                task_id=task_id,
                turn=turn,
                event_type=HistoryEventType.TOOL_END,
                payload={
                    "tool_call": _serialize_tool_call(tool_call),
                    "result": truncated_result,
                    "is_error": is_error,
                    "result_truncated": was_truncated,
                    "original_result_chars": len(result),
                },
            )
        )

    def list_session_events(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        limit: int = 200,
        newest_first: bool = False,
    ) -> list[HistoryEventRecord]:
        return self.store.list_events(
            session_id=session_id,
            run_id=run_id,
            limit=limit,
            newest_first=newest_first,
        )

    def _append(self, record: HistoryEventRecord) -> None:
        try:
            self.store.append(record)
        except Exception:
            logger.exception(
                "lossless_history_append_failed event_type=%s session_id=%s run_id=%s",
                record.event_type.value,
                record.session_id,
                record.run_id,
            )


def _serialize_tool_call(tool_call: ToolCall) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": tool_call.id,
        "name": tool_call.name,
        "input": _sanitize_for_json(tool_call.input),
    }
    return payload


def _sanitize_for_json(value: Any) -> Any:
    if is_dataclass(value):
        return _sanitize_for_json(asdict(value))
    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in value]
    return value
