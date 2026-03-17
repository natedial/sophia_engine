"""Claude Code-backed delegated coding worker."""

from __future__ import annotations

import asyncio
import json

from sophia.coding_workers.base import BaseCodingWorker, CodingWorkerExecution, output_schema
from sophia_forge_protocol.run_models import RunRequest


class ClaudeCodeWorker(BaseCodingWorker):
    """Run Claude Code headlessly in a bounded workspace."""

    backend_name = "claude_code"

    async def run_request(self, request: RunRequest) -> CodingWorkerExecution:
        disabled = self._disabled_execution()
        if disabled is not None:
            return disabled

        resolved_bin = self._resolve_binary(
            self.settings.claude_code_command,
        )
        if resolved_bin is None:
            return CodingWorkerExecution(
                status="unavailable",
                summary="",
                error=f"Claude Code CLI not found on PATH: {self.settings.claude_code_command}",
            )

        workspace_root, _, add_dirs = self._prepare_workspace(request)
        prompt = self._build_prompt(
            request=request,
            workspace_root=workspace_root,
            add_dirs=add_dirs,
        )
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
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=max(0.1, request.timeout_sec),
            )
        except TimeoutError:
            return CodingWorkerExecution(
                status="timed_out",
                summary="",
                error="Claude Code worker timed out",
            )
        except PermissionError as exc:
            return CodingWorkerExecution(
                status="permission_denied",
                summary="",
                error=str(exc),
            )
        except Exception as exc:
            return CodingWorkerExecution(
                status="failed",
                summary="",
                error=f"Claude Code worker launch failed: {exc}",
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            return CodingWorkerExecution(
                status="failed",
                summary="",
                raw_message=stdout_text[: self.settings.coding_worker_max_message_chars],
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
        return parsed

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
