"""CLI wrapper for the official Readwise command-line tool."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReadwiseCommandResult:
    """Result of a Readwise CLI invocation."""

    returncode: int
    stdout: str
    stderr: str
    argv: list[str]


class ReadwiseClient:
    """Wrapper around the installed `readwise` CLI."""

    def __init__(
        self,
        cli_path: str = "readwise",
        config_path: str = "~/.readwise-cli.json",
        timeout: float = 30.0,
    ) -> None:
        self.cli_path = cli_path.strip() or "readwise"
        self.config_path = Path(config_path).expanduser()
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "readwise"

    @property
    def resolved_cli_path(self) -> str | None:
        raw = self.cli_path
        if "/" in raw:
            path = Path(raw).expanduser()
            return str(path) if path.exists() else None
        return shutil.which(raw)

    @property
    def is_installed(self) -> bool:
        return self.resolved_cli_path is not None

    @property
    def is_configured(self) -> bool:
        config = self._load_config()
        return bool(config.get("access_token"))

    async def close(self) -> None:
        return None

    async def health_check(self) -> bool:
        if not self.is_installed or not self.is_configured:
            return False
        try:
            result = await self.run_raw(["--help"])
        except Exception:
            return False
        return result.returncode == 0

    async def refresh_tools_cache(self) -> ReadwiseCommandResult:
        return await self.run_raw(["--refresh", "help"])

    def list_cached_tools(self) -> list[dict[str, Any]]:
        config = self._load_config()
        cached = config.get("tools_cache", {})
        tools = cached.get("tools", [])
        if not isinstance(tools, list):
            return []

        rows: list[dict[str, Any]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "tool_name": name,
                    "command": name.replace("_", "-"),
                    "description": item.get("description"),
                    "read_only": bool((item.get("annotations") or {}).get("readOnlyHint")),
                    "input_schema": item.get("inputSchema") or {},
                }
            )
        return rows

    async def run_raw(
        self,
        args: list[str],
        *,
        json_output: bool = False,
    ) -> ReadwiseCommandResult:
        cli = self.resolved_cli_path
        if cli is None:
            raise FileNotFoundError(f"Readwise CLI not found: {self.cli_path}")

        argv = [cli]
        if json_output:
            argv.append("--json")
        argv.extend(args)

        env = os.environ.copy()
        env["HOME"] = str(self.config_path.parent)

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise

        return ReadwiseCommandResult(
            returncode=int(process.returncode or 0),
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            argv=argv,
        )

    def config_summary(self) -> dict[str, Any]:
        config = self._load_config()
        readonly = bool((config.get("config") or {}).get("readonly", False))
        return {
            "cli_path": self.resolved_cli_path,
            "config_path": str(self.config_path),
            "installed": self.is_installed,
            "configured": bool(config.get("access_token")),
            "readonly": readonly,
            "cached_tool_count": len(self.list_cached_tools()),
        }

    def _load_config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
