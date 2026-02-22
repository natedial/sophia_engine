"""Base tool definitions and types."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolParameterType(str, Enum):
    """Supported parameter types for tool definitions."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class ErrorType(str, Enum):
    """Classification of tool execution errors."""

    # Transient - may succeed on retry
    SERVICE_UNAVAILABLE = "service_unavailable"  # Service is down or unreachable
    TIMEOUT = "timeout"  # Request timed out
    RATE_LIMITED = "rate_limited"  # Too many requests

    # Permanent - won't succeed without changes
    NOT_FOUND = "not_found"  # Resource doesn't exist (e.g., invalid series ID)
    INVALID_INPUT = "invalid_input"  # Bad parameters provided
    UNAUTHORIZED = "unauthorized"  # Auth/permission issue

    # Internal
    UNKNOWN = "unknown"  # Unclassified error


# Recovery hints for each error type - helps LLM decide what to do
ERROR_RECOVERY_HINTS: dict[ErrorType, str] = {
    ErrorType.SERVICE_UNAVAILABLE: "The data service is currently unavailable. Inform the user and suggest trying again later.",
    ErrorType.TIMEOUT: "The request timed out. You may retry once, or inform the user of delays.",
    ErrorType.RATE_LIMITED: "Too many requests. Wait briefly before retrying.",
    ErrorType.NOT_FOUND: "The requested resource was not found. Check if the identifier (e.g., series_id) is correct. Use search_series to find valid identifiers.",
    ErrorType.INVALID_INPUT: "The parameters provided were invalid. Review the tool's expected inputs and correct them.",
    ErrorType.UNAUTHORIZED: "Access denied. This may require configuration changes. Inform the user.",
    ErrorType.UNKNOWN: "An unexpected error occurred. Inform the user and suggest trying a different approach.",
}


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""

    name: str
    type: ToolParameterType
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None


@dataclass
class ToolDefinition:
    """Definition of a tool that can be called by an LLM."""

    name: str
    description: str
    parameters: list[ToolParameter]

    def to_anthropic_schema(self) -> dict[str, Any]:
        """Convert to Anthropic tool schema format."""
        properties = {}
        required = []

        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type.value,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def to_generic_schema(self) -> dict[str, Any]:
        """Provider-agnostic schema with name, description, input_schema."""
        schema = self.to_anthropic_schema()
        return {
            "name": schema["name"],
            "description": schema["description"],
            "input_schema": schema["input_schema"],
        }


@dataclass
class ToolResult:
    """Result of executing a tool."""

    success: bool
    data: Any = None
    error: str | None = None
    error_type: ErrorType | None = None

    @property
    def is_retryable(self) -> bool:
        """Check if this error is transient and may succeed on retry."""
        return self.error_type in (
            ErrorType.SERVICE_UNAVAILABLE,
            ErrorType.TIMEOUT,
            ErrorType.RATE_LIMITED,
        )

    def to_content(self) -> str:
        """Convert to string content for LLM consumption.

        For errors, includes the error type and recovery hint to help
        the LLM decide how to proceed.
        """
        if self.success:
            if isinstance(self.data, str):
                return self.data
            return str(self.data)

        # Build informative error message for LLM
        parts = [f"Error: {self.error}"]

        if self.error_type:
            parts.append(f"Error type: {self.error_type.value}")
            hint = ERROR_RECOVERY_HINTS.get(self.error_type)
            if hint:
                parts.append(f"Recovery hint: {hint}")

        return "\n".join(parts)

    @classmethod
    def ok(cls, data: Any) -> "ToolResult":
        """Create a successful result."""
        return cls(success=True, data=data)

    @classmethod
    def fail(
        cls,
        error: str,
        error_type: ErrorType = ErrorType.UNKNOWN,
    ) -> "ToolResult":
        """Create a failed result with error classification."""
        return cls(success=False, error=error, error_type=error_type)
