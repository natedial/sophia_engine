"""Pylon - Main gateway interface for backend services."""

import asyncio
import importlib
import time
from dataclasses import dataclass, field
from typing import Any

from pylon.clients.arithmos import ArithmosClient
from pylon.clients.brave import BraveClient
from pylon.clients.canvas import CanvasClient
from pylon.clients.fed_tracker import FedTrackerClient
from pylon.clients.oikonomia import OikonomiaClient
from pylon.clients.readwise import ReadwiseClient
from pylon.clients.scrivener import ScrivenerClient
from pylon.clients.tholos import TholosClient
from pylon.tools.arithmos import ArithmosToolExecutor
from pylon.tools.base import ErrorType, ToolDefinition, ToolResult
from pylon.tools.brave import BraveToolExecutor
from pylon.tools.canvas import CanvasToolExecutor
from pylon.tools.fed_tracker import FedTrackerToolExecutor
from pylon.tools.oikonomia import OikonomiaToolExecutor
from pylon.tools.readwise import ReadwiseToolExecutor
from pylon.tools.scrivener import ScrivenerToolExecutor
from pylon.tools.tholos import TholosToolExecutor


@dataclass
class PylonConfig:
    """Configuration for Pylon gateway."""

    scrivener_url: str = "http://localhost:8000"
    scrivener_api_key: str = ""
    arithmos_url: str = "http://localhost:8001"
    canvas_url: str = "http://localhost:8003"
    tholos_url: str = "http://localhost:8004"
    fed_tracker_url: str = "http://127.0.0.1:8005"
    oikonomia_url: str = "http://localhost:8006"
    readwise_cli_path: str = "readwise"
    readwise_cli_config_path: str = "~/.readwise-cli.json"
    brave_base_url: str = "https://api.search.brave.com"
    brave_api_key: str = ""
    max_concurrency_per_service: int = 8
    tool_timeout_sec: float = 30.0


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


@dataclass(frozen=True)
class _ExecutorSpec:
    service_name: str
    executor_attr: str
    module_name: str
    class_name: str
    dependency_attrs: tuple[str, ...]


_EXECUTOR_SPECS: tuple[_ExecutorSpec, ...] = (
    _ExecutorSpec(
        service_name="brave",
        executor_attr="_brave_executor",
        module_name="pylon.tools.brave",
        class_name="BraveToolExecutor",
        dependency_attrs=("_brave_client",),
    ),
    _ExecutorSpec(
        service_name="scrivener",
        executor_attr="_scrivener_executor",
        module_name="pylon.tools.scrivener",
        class_name="ScrivenerToolExecutor",
        dependency_attrs=("_scrivener_client",),
    ),
    _ExecutorSpec(
        service_name="arithmos",
        executor_attr="_arithmos_executor",
        module_name="pylon.tools.arithmos",
        class_name="ArithmosToolExecutor",
        dependency_attrs=("_arithmos_client",),
    ),
    _ExecutorSpec(
        service_name="canvas",
        executor_attr="_canvas_executor",
        module_name="pylon.tools.canvas",
        class_name="CanvasToolExecutor",
        dependency_attrs=("_canvas_client", "_scrivener_client"),
    ),
    _ExecutorSpec(
        service_name="tholos",
        executor_attr="_tholos_executor",
        module_name="pylon.tools.tholos",
        class_name="TholosToolExecutor",
        dependency_attrs=("_tholos_client",),
    ),
    _ExecutorSpec(
        service_name="fed_tracker",
        executor_attr="_fed_tracker_executor",
        module_name="pylon.tools.fed_tracker",
        class_name="FedTrackerToolExecutor",
        dependency_attrs=("_fed_tracker_client",),
    ),
    _ExecutorSpec(
        service_name="oikonomia",
        executor_attr="_oikonomia_executor",
        module_name="pylon.tools.oikonomia",
        class_name="OikonomiaToolExecutor",
        dependency_attrs=("_oikonomia_client",),
    ),
    _ExecutorSpec(
        service_name="readwise",
        executor_attr="_readwise_executor",
        module_name="pylon.tools.readwise",
        class_name="ReadwiseToolExecutor",
        dependency_attrs=("_readwise_client",),
    ),
)


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
        scrivener_headers = (
            {"X-Scrivener-API-Key": self.config.scrivener_api_key}
            if self.config.scrivener_api_key
            else None
        )
        self._scrivener_client = ScrivenerClient(
            base_url=self.config.scrivener_url,
            headers=scrivener_headers,
        )
        self._arithmos_client = ArithmosClient(base_url=self.config.arithmos_url)
        self._canvas_client = CanvasClient(base_url=self.config.canvas_url)
        self._tholos_client = TholosClient(base_url=self.config.tholos_url)
        self._fed_tracker_client = FedTrackerClient(base_url=self.config.fed_tracker_url)
        self._oikonomia_client = OikonomiaClient(base_url=self.config.oikonomia_url)
        self._readwise_client = ReadwiseClient(
            cli_path=self.config.readwise_cli_path,
            config_path=self.config.readwise_cli_config_path,
            timeout=self.config.tool_timeout_sec,
        )
        self._brave_client = BraveClient(
            base_url=self.config.brave_base_url,
            api_key=self.config.brave_api_key,
        )

        self._service_executors: dict[str, Any] = {}
        self._build_tool_executors()

        # Build tool routing table: tool_name -> (executor, service_name)
        self._tool_executors: dict[str, tuple[Any, str]] = {}
        self._service_tools: dict[str, list[str]] = {}  # service_name -> [tool_names]
        self._register_tools()

        # Track service health status (updated by preflight)
        self._service_status: dict[str, ServiceStatus] = {}
        self._service_semaphores: dict[str, asyncio.Semaphore] = {
            service_name: asyncio.Semaphore(max(1, self.config.max_concurrency_per_service))
            for service_name in self._service_tools
        }

    def _build_tool_executors(self, *, reload_modules: bool = False) -> None:
        """Build executor instances from service specs."""
        self._service_executors = {}
        for spec in _EXECUTOR_SPECS:
            module = importlib.import_module(spec.module_name)
            if reload_modules:
                module = importlib.reload(module)
            executor_cls = getattr(module, spec.class_name)
            deps = [getattr(self, attr) for attr in spec.dependency_attrs]
            executor = executor_cls(*deps)
            setattr(self, spec.executor_attr, executor)
            self._service_executors[spec.service_name] = executor

    def _register_tools(self) -> None:
        """Register all tools from all services."""
        self._tool_executors = {}
        self._service_tools = {}
        for service_name, executor in self._service_executors.items():
            tool_names: list[str] = []
            for tool in executor.get_tools():
                self._tool_executors[tool.name] = (executor, service_name)
                tool_names.append(tool.name)
            self._service_tools[service_name] = tool_names

    def refresh_tools(self, *, reload_modules: bool = True) -> list[str]:
        """Rebuild tool executors and refresh the live tool registry."""
        self._build_tool_executors(reload_modules=reload_modules)
        self._register_tools()
        self._service_semaphores = {
            service_name: asyncio.Semaphore(max(1, self.config.max_concurrency_per_service))
            for service_name in self._service_tools
        }
        return sorted(self._tool_executors.keys())

    async def close(self) -> None:
        """Close all client connections."""
        await self._scrivener_client.close()
        await self._arithmos_client.close()
        await self._canvas_client.close()
        await self._tholos_client.close()
        await self._fed_tracker_client.close()
        await self._oikonomia_client.close()
        await self._readwise_client.close()
        await self._brave_client.close()

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
            elif name == "canvas":
                healthy = await self._canvas_client.health_check()
            elif name == "tholos":
                healthy = await self._tholos_client.health_check()
            elif name == "fed_tracker":
                healthy = await self._fed_tracker_client.health_check()
            elif name == "oikonomia":
                healthy = await self._oikonomia_client.health_check()
            elif name == "readwise":
                healthy = await self._readwise_client.health_check()
            elif name == "brave":
                healthy = await self._brave_client.health_check()
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
        for service_name, executor in self._service_executors.items():
            for tool in executor.get_tools():
                if only_healthy:
                    status = self._service_status.get(service_name)
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

    async def execute_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        on_update: Any | None = None,
    ) -> ToolResult:
        """
        Execute a tool by name.

        This is the main interface for LLM consumers - they just call tools
        by name and Pylon routes to the appropriate service.

        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters
            on_update: Optional callback for progress updates (extension point)

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

        semaphore = self._service_semaphores.get(service_name)
        if semaphore is None:
            return ToolResult.fail(
                f"No concurrency guard configured for service '{service_name}'",
                ErrorType.UNKNOWN,
            )

        try:
            async with semaphore:
                result = await asyncio.wait_for(
                    executor.execute(tool_name, parameters),
                    timeout=max(0.1, self.config.tool_timeout_sec),
                )
                if (
                    not result.success
                    and result.error_type in {ErrorType.SERVICE_UNAVAILABLE, ErrorType.TIMEOUT}
                ):
                    self._service_status[service_name] = ServiceStatus(
                        name=service_name,
                        healthy=False,
                        error=result.error or "Runtime tool failure",
                    )
                return result
        except TimeoutError:
            self._service_status[service_name] = ServiceStatus(
                name=service_name,
                healthy=False,
                error=f"Tool timeout after {self.config.tool_timeout_sec:.1f}s",
            )
            return ToolResult.fail(
                f"Tool '{tool_name}' timed out after {self.config.tool_timeout_sec:.1f}s",
                ErrorType.TIMEOUT,
            )

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

    @property
    def canvas(self) -> CanvasClient:
        """Direct access to Canvas client for non-LLM use cases."""
        return self._canvas_client

    @property
    def tholos(self) -> TholosClient:
        """Direct access to Tholos client for non-LLM use cases."""
        return self._tholos_client

    @property
    def fed_tracker(self) -> FedTrackerClient:
        """Direct access to Fed Tracker client for non-LLM use cases."""
        return self._fed_tracker_client

    @property
    def oikonomia(self) -> OikonomiaClient:
        """Direct access to Oikonomia client for non-LLM use cases."""
        return self._oikonomia_client

    @property
    def brave(self) -> BraveClient:
        """Direct access to Brave client for non-LLM use cases."""
        return self._brave_client

    @property
    def readwise(self) -> ReadwiseClient:
        """Direct access to Readwise client for non-LLM use cases."""
        return self._readwise_client
