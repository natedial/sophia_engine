"""Pylon - Main gateway interface for backend services."""

import time
from dataclasses import dataclass, field
from typing import Any

from pylon.clients.arithmos import ArithmosClient
from pylon.clients.scrivener import ScrivenerClient
from pylon.tools.arithmos import ArithmosToolExecutor
from pylon.tools.base import ErrorType, ToolDefinition, ToolResult
from pylon.tools.scrivener import ScrivenerToolExecutor


@dataclass
class PylonConfig:
    """Configuration for Pylon gateway."""

    scrivener_url: str = "http://localhost:8000"
    arithmos_url: str = "http://localhost:8001"
    # Future services:
    # kampe_url: str = "http://localhost:8002"


@dataclass
class ServiceStatus:
    """Detailed health status for a service."""

    name: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None
    last_checked: float = field(default_factory=time.time)

    @property
    def status_summary(self) -> str:
        """Human-readable status summary."""
        if self.healthy:
            return f"{self.name}: healthy ({self.latency_ms:.0f}ms)"
        return f"{self.name}: unavailable - {self.error}"


@dataclass
class PreflightResult:
    """Result of pre-flight checks."""

    all_healthy: bool
    services: dict[str, ServiceStatus]
    available_tools: list[str]
    unavailable_tools: list[str]

    def summary(self) -> str:
        """Human-readable summary for logging/display."""
        lines = ["Pre-flight check:"]
        for status in self.services.values():
            icon = "✓" if status.healthy else "✗"
            lines.append(f"  {icon} {status.status_summary}")

        if self.unavailable_tools:
            lines.append(f"  Unavailable tools: {', '.join(self.unavailable_tools)}")

        return "\n".join(lines)

    def for_system_prompt(self) -> str | None:
        """Generate context for LLM system prompt about service status.

        Returns None if all services are healthy (no need to mention).
        """
        if self.all_healthy:
            return None

        parts = ["SERVICE STATUS:"]
        for status in self.services.values():
            if not status.healthy:
                parts.append(f"- {status.name} is currently unavailable: {status.error}")

        if self.unavailable_tools:
            parts.append(f"- The following tools are disabled: {', '.join(self.unavailable_tools)}")
            parts.append("- If the user asks for data from unavailable services, explain the limitation.")

        return "\n".join(parts)


class Pylon:
    """
    Gateway layer for backend service integration.

    Pylon is the single point of contact for all backend services.
    Consumers (like sophia_prima) talk to Pylon, not individual services.

    Responsibilities:
    - Manages connections to backend services
    - Provides unified tool interface for LLM consumers
    - Routes tool calls to appropriate services
    - Handles errors and health checks
    - Pre-flight checks before tool execution
    """

    def __init__(self, config: PylonConfig | None = None) -> None:
        self.config = config or PylonConfig()

        # Initialize clients
        self._scrivener_client = ScrivenerClient(base_url=self.config.scrivener_url)
        self._arithmos_client = ArithmosClient(base_url=self.config.arithmos_url)

        # Initialize tool executors
        self._scrivener_executor = ScrivenerToolExecutor(self._scrivener_client)
        self._arithmos_executor = ArithmosToolExecutor(self._arithmos_client)

        # Build tool routing table: tool_name -> (executor, service_name)
        self._tool_executors: dict[str, tuple[Any, str]] = {}
        self._service_tools: dict[str, list[str]] = {}  # service_name -> [tool_names]
        self._register_tools()

        # Track service health status (updated by preflight)
        self._service_status: dict[str, ServiceStatus] = {}

    def _register_tools(self) -> None:
        """Register all tools from all services."""
        # Register Scrivener tools
        scrivener_tools = []
        for tool in self._scrivener_executor.get_tools():
            self._tool_executors[tool.name] = (self._scrivener_executor, "scrivener")
            scrivener_tools.append(tool.name)
        self._service_tools["scrivener"] = scrivener_tools

        # Register Arithmos tools
        arithmos_tools = []
        for tool in self._arithmos_executor.get_tools():
            self._tool_executors[tool.name] = (self._arithmos_executor, "arithmos")
            arithmos_tools.append(tool.name)
        self._service_tools["arithmos"] = arithmos_tools

    async def close(self) -> None:
        """Close all client connections."""
        await self._scrivener_client.close()
        await self._arithmos_client.close()

    # -------------------------------------------------------------------------
    # Health Checks & Pre-flight
    # -------------------------------------------------------------------------

    async def health_check(self) -> dict[str, bool]:
        """Simple health check of all backend services (legacy interface)."""
        result = await self.preflight()
        return {name: status.healthy for name, status in result.services.items()}

    async def _check_service_health(self, name: str) -> ServiceStatus:
        """Check health of a single service with timing."""
        start = time.time()
        try:
            if name == "scrivener":
                healthy = await self._scrivener_client.health_check()
            elif name == "arithmos":
                healthy = await self._arithmos_client.health_check()
            else:
                healthy = False

            latency_ms = (time.time() - start) * 1000

            if healthy:
                return ServiceStatus(name=name, healthy=True, latency_ms=latency_ms)
            else:
                return ServiceStatus(
                    name=name,
                    healthy=False,
                    latency_ms=latency_ms,
                    error="Health check returned unhealthy",
                )
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            return ServiceStatus(
                name=name,
                healthy=False,
                latency_ms=latency_ms,
                error=str(e),
            )

    async def preflight(self) -> PreflightResult:
        """
        Run pre-flight checks on all services.

        Returns detailed status including:
        - Per-service health with latency
        - Which tools are available vs unavailable
        - Summary suitable for system prompt injection

        Call this before starting a conversation to know what's available.
        """
        # Check all services
        services: dict[str, ServiceStatus] = {}
        for service_name in self._service_tools.keys():
            status = await self._check_service_health(service_name)
            services[service_name] = status
            self._service_status[service_name] = status

        # Determine available/unavailable tools
        available_tools: list[str] = []
        unavailable_tools: list[str] = []

        for service_name, tool_names in self._service_tools.items():
            if services[service_name].healthy:
                available_tools.extend(tool_names)
            else:
                unavailable_tools.extend(tool_names)

        all_healthy = all(s.healthy for s in services.values())

        return PreflightResult(
            all_healthy=all_healthy,
            services=services,
            available_tools=available_tools,
            unavailable_tools=unavailable_tools,
        )

    # -------------------------------------------------------------------------
    # Tool Interface (for LLM consumers)
    # -------------------------------------------------------------------------

    def get_tools(self, only_healthy: bool = False) -> list[ToolDefinition]:
        """Get available tool definitions.

        Args:
            only_healthy: If True, only return tools from healthy services
                          (requires preflight() to have been called)

        Returns:
            List of tool definitions
        """
        tools = []

        # Scrivener tools
        for tool in self._scrivener_executor.get_tools():
            if only_healthy:
                status = self._service_status.get("scrivener")
                if status and not status.healthy:
                    continue
            tools.append(tool)

        # Arithmos tools
        for tool in self._arithmos_executor.get_tools():
            if only_healthy:
                status = self._service_status.get("arithmos")
                if status and not status.healthy:
                    continue
            tools.append(tool)

        return tools

    def get_tools_as_anthropic_schema(self, only_healthy: bool = False) -> list[dict[str, Any]]:
        """Get tools formatted for Anthropic API.

        Args:
            only_healthy: If True, only return tools from healthy services
        """
        return [tool.to_anthropic_schema() for tool in self.get_tools(only_healthy=only_healthy)]

    async def execute_tool(self, tool_name: str, parameters: dict[str, Any]) -> ToolResult:
        """
        Execute a tool by name.

        This is the main interface for LLM consumers - they just call tools
        by name and Pylon routes to the appropriate service.

        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters

        Returns:
            Result of the tool execution
        """
        tool_info = self._tool_executors.get(tool_name)
        if tool_info is None:
            return ToolResult.fail(f"Unknown tool: {tool_name}", ErrorType.INVALID_INPUT)

        executor, service_name = tool_info

        # Check if service is known to be unhealthy (if preflight was run)
        status = self._service_status.get(service_name)
        if status and not status.healthy:
            return ToolResult.fail(
                f"Service '{service_name}' is currently unavailable: {status.error}",
                ErrorType.SERVICE_UNAVAILABLE,
            )

        return await executor.execute(tool_name, parameters)

    # -------------------------------------------------------------------------
    # Direct Client Access (for non-LLM consumers)
    # -------------------------------------------------------------------------

    @property
    def scrivener(self) -> ScrivenerClient:
        """Direct access to Scrivener client for non-LLM use cases."""
        return self._scrivener_client

    @property
    def arithmos(self) -> ArithmosClient:
        """Direct access to Arithmos client for non-LLM use cases."""
        return self._arithmos_client
