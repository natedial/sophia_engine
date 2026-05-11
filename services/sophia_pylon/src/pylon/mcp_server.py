"""Streamable HTTP MCP server for Sophia Pylon."""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pylon import Pylon
from pylon.mcp_bridge import call_mcp_tool, list_mcp_tool_specs, pylon_config_from_env

logger = logging.getLogger("pylon.mcp_server")


def create_pylon_from_env(env: dict[str, str] | None = None) -> Pylon:
    """Create a Pylon instance from environment variables."""
    return Pylon(pylon_config_from_env(env or os.environ))


def create_app(
    *,
    pylon: Pylon | None = None,
    path: str = "/mcp",
    json_response: bool = True,
    debug: bool = False,
) -> Any:
    """Create the Starlette ASGI app that serves Pylon over MCP."""
    try:
        import mcp.types as types
        from mcp.server.lowlevel import Server
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.middleware.cors import CORSMiddleware
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route
        from starlette.types import Receive, Scope, Send
    except ImportError as exc:  # pragma: no cover - exercised only without optional extra
        raise RuntimeError(
            "The MCP server requires the optional dependency extra: "
            "install sophia-pylon[mcp]."
        ) from exc

    owned_pylon = pylon or create_pylon_from_env()
    server = Server("sophia-pylon")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.input_schema,
            )
            for tool in list_mcp_tool_specs(owned_pylon)
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[types.ContentBlock]:
        text = await call_mcp_tool(owned_pylon, name, arguments)
        return [types.TextContent(type="text", text=text)]

    session_manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=json_response,
        stateless=True,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    async def health(_request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok", "mcp_path": path})

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            try:
                yield
            finally:
                await owned_pylon.close()

    app = Starlette(
        debug=debug,
        routes=[
            Mount(path, app=handle_streamable_http),
            Route("/health", endpoint=health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )
    return CORSMiddleware(
        app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE"],
        expose_headers=["Mcp-Session-Id"],
    )


def main(argv: list[str] | None = None) -> int:
    """Run the Pylon MCP server."""
    parser = argparse.ArgumentParser(description="Serve Sophia Pylon tools over MCP.")
    parser.add_argument("--host", default=os.environ.get("PYLON_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PYLON_MCP_PORT", "8091")))
    parser.add_argument("--path", default=os.environ.get("PYLON_MCP_PATH", "/mcp"))
    parser.add_argument(
        "--log-level",
        default=os.environ.get("PYLON_MCP_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument(
        "--sse-response",
        action="store_true",
        help="Use SSE responses instead of JSON responses.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = create_app(path=args.path, json_response=not args.sse_response)

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - exercised only without optional extra
        raise RuntimeError(
            "The MCP server requires uvicorn from the optional dependency extra: "
            "install sophia-pylon[mcp]."
        ) from exc

    logger.info(
        "Starting Sophia Pylon MCP server on http://%s:%s%s",
        args.host,
        args.port,
        args.path,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
