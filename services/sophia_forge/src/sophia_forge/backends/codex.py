"""Native Codex backend for forge."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

from sophia_forge.backends.base import BaseForgeBackend, output_schema
from sophia_forge_protocol.run_models import RunRequest, RunResult


class CodexBackend(BaseForgeBackend):
    """Run Codex CLI for a forge coding task."""

    backend_name = "codex"

    async def run(self, request: RunRequest, *, env: Mapping[str, str] | None = None) -> RunResult:
        resolved_bin = self._resolve_binary(self.settings.codex_command)
        if resolved_bin is None:
            return RunResult(
                run_id=request.run_id,
                status="unavailable",
                summary="",
                error=f"Codex CLI not found on PATH: {self.settings.codex_command}",
            )

        task_id = (request.run_id or "forge_run").replace(":", "_")
        workspace_root, output_dir, add_dirs = self._prepare_paths(request)
        schema_path = output_dir / f"{task_id}_schema.json"
        last_message_path = output_dir / f"{task_id}_last_message.json"
        schema_path.write_text(json.dumps(output_schema(), indent=2), encoding="utf-8")
        if last_message_path.exists():
            last_message_path.unlink()

        prompt = self._build_prompt(request=request, workspace_root=workspace_root, add_dirs=add_dirs)
        command = self._build_command(
            codex_bin=resolved_bin,
            workspace_root=workspace_root,
            add_dirs=add_dirs,
            schema_path=schema_path,
            last_message_path=last_message_path,
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
                error="Codex backend timed out",
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
                error=f"Codex backend launch failed: {exc}",
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if last_message_path.exists():
            parsed = self._parse_structured_output(
                last_message_path.read_text(encoding="utf-8").strip(),
                invalid_json_error="Codex backend returned non-JSON output",
                invalid_root_error="Codex backend output schema root must be an object",
                failure_prefix="Codex",
            )
            success = process.returncode == 0 and parsed.status == "completed"
            error = None
            if process.returncode != 0:
                error = self._format_failure(
                    backend_label="Codex",
                    return_code=process.returncode,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                )
            elif not success:
                error = parsed.error or f"Codex finished with status={parsed.status}"
            return parsed.model_copy(
                update={
                    "run_id": request.run_id,
                    "success": success,
                    "error": error,
                }
            )

        return RunResult(
            run_id=request.run_id,
            status="failed",
            summary="",
            raw_message=stdout_text[: self.settings.max_message_chars],
            error=self._format_failure(
                backend_label="Codex",
                return_code=process.returncode,
                stdout_text=stdout_text,
                stderr_text=stderr_text,
            ),
        )

    def _build_command(
        self,
        *,
        codex_bin: str,
        workspace_root: Path,
        add_dirs: tuple[Path, ...],
        schema_path: Path,
        last_message_path: Path,
        prompt: str,
    ) -> list[str]:
        command = [
            codex_bin,
            "exec",
            "--full-auto",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "-s",
            self.settings.codex_sandbox,
            "-C",
            str(workspace_root),
            "--output-schema",
            str(schema_path),
            "-o",
            str(last_message_path),
        ]
        if self.settings.codex_model.strip():
            command.extend(["-m", self.settings.codex_model.strip()])
        for add_dir in add_dirs:
            command.extend(["--add-dir", str(add_dir)])
        command.append(prompt)
        return command
