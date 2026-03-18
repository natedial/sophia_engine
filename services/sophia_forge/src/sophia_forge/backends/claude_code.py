"""Native Claude Code backend for forge."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping

from sophia_forge.backends.base import BaseForgeBackend, output_schema
from sophia_forge_protocol.run_models import RunRequest, RunResult


class ClaudeCodeBackend(BaseForgeBackend):
    """Run Claude Code headlessly for a forge coding task."""

    backend_name = "claude_code"

    async def run(self, request: RunRequest, *, env: Mapping[str, str] | None = None) -> RunResult:
        resolved_bin = self._resolve_binary(self.settings.claude_code_command)
        if resolved_bin is None:
            return RunResult(
                run_id=request.run_id,
                status="unavailable",
                summary="",
                error=f"Claude Code CLI not found on PATH: {self.settings.claude_code_command}",
            )

        workspace_root, _, add_dirs = self._prepare_paths(request)
        prompt = self._build_prompt(request=request, workspace_root=workspace_root, add_dirs=add_dirs)
        command = self._build_command(
            claude_bin=resolved_bin,
            request=request,
            add_dirs=add_dirs,
            prompt=prompt,
        )

        try:
            process = await self.process_factory(
                *command,
                cwd=str(workspace_root),
                env=None if env is None else dict(env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(0.1, request.timeout_sec),
            )
        except TimeoutError:
            return RunResult(
                run_id=request.run_id,
                status="timed_out",
                summary="",
                error="Claude Code backend timed out",
            )
        except PermissionError as exc:
            return RunResult(
                run_id=request.run_id,
                status="permission_denied",
                summary="",
                error=str(exc),
            )
        except Exception as exc:
            return RunResult(
                run_id=request.run_id,
                status="failed",
                summary="",
                error=f"Claude Code backend launch failed: {exc}",
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            return RunResult(
                run_id=request.run_id,
                status="failed",
                summary="",
                raw_message=stdout_text[: self.settings.max_message_chars],
                error=self._format_failure(
                    backend_label="Claude Code",
                    return_code=process.returncode,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                ),
            )

        parsed = self._parse_structured_output(
            stdout_text,
            invalid_json_error="Claude Code returned non-JSON structured output",
            invalid_root_error="Claude Code structured output root must be an object",
            failure_prefix="Claude Code",
        )
        return parsed.model_copy(update={"run_id": request.run_id})

    def _build_command(
        self,
        *,
        claude_bin: str,
        request: RunRequest,
        add_dirs: tuple,
        prompt: str,
    ) -> list[str]:
        command = [claude_bin]
        if self.settings.claude_code_model.strip():
            command.extend(["--model", self.settings.claude_code_model.strip()])
        if add_dirs:
            command.extend(["--add-dir", *[str(path) for path in add_dirs]])
        command.extend(
            [
                "--json-schema",
                json.dumps(output_schema(), separators=(",", ":")),
                "--permission-mode",
                self.settings.claude_code_permission_mode,
                "--allowedTools",
                ",".join(request.execution_policy.backend_allowed_tools)
                or self.settings.claude_code_allowed_tools,
                "--max-turns",
                str(self.settings.claude_code_max_turns),
                "--append-system-prompt",
                "Return only valid JSON matching the provided schema.",
                "-p",
                prompt,
            ]
        )
        return command
