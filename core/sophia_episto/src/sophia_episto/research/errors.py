"""Typed protocol errors for the research-case surface."""

from __future__ import annotations

from enum import Enum


class ProtocolErrorCode(str, Enum):
    CONFLICT = "conflict"
    STALE_REVISION = "stale_revision"
    NOT_FOUND = "not_found"
    INVALID_EVIDENCE = "invalid_evidence"
    UNMET_REQUIREMENTS = "unmet_requirements"
    METHOD_UNAVAILABLE = "method_unavailable"
    UNSUPPORTED_QUESTION = "unsupported_question"
    INVALID_REQUEST = "invalid_request"


class ProtocolError(Exception):
    """Structured failure returned to an outside agent."""

    def __init__(
        self,
        code: ProtocolErrorCode,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
            }
        }
