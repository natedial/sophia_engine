"""Codex-backed delegated coding worker."""

from __future__ import annotations

import asyncio
import json

from sophia.coding_workers.base import BaseCodingWorker, CodingWorkerExecution, output_schema
from sophia_forge_protocol.run_models import RunRequest


class CodexCodingWorker(BaseCodingWorker):
    """Run Codex CLI in a bounded workspace for implementation tasks."""

    backend_name = "codex"

    async def run_request(self, request: RunRequest) -> CodingWorkerExecution:
        disabled = self._disabled_execution()
        if disabled is not None:
            return disabled

        resolved_bin = self._resolve_binary(
            self.settings.codex_command,
        )
        if resolved_bin is None:
            return CodingWorkerExecution(
                status="unavailable",
                summary="",
                error=f"Codex CLI not found on PATH: {self.settings.codex_command}",
            )

        task_id = (request.run_id or "forge_run").replace(":", "_")
        workspace_root, output_dir, add_dirs = self._prepare_workspace(request)
        schema_path = output_dir / f"{task_id}_schema.json"
        last_message_path = output_dir / f"{task_id}_last_message.json"
        schema_path.write_text(json.dumps(output_schema(), indent=2), encoding="utf-8")
        if last_message_path.exists():
            last_message_path.unlink()

        prompt = self._build_prompt(
            request=request,
            workspace_root=workspace_root,
            add_dirs=add_dirs,
        )
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
                error="Codex coding worker timed out",
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
                error=f"Codex coding worker launch failed: {exc}",
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if last_message_path.exists():
            parsed = self._parse_structured_output(
                last_message_path.read_text(encoding="utf-8").strip(),
                invalid_json_error="Codex coding worker returned non-JSON output",
                invalid_root_error="Codex coding worker output schema root must be an object",
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
            return CodingWorkerExecution(
                success=success,
                status=parsed.status,
                summary=parsed.summary,
                changed_files=parsed.changed_files,
                verification=parsed.verification,
                follow_ups=parsed.follow_ups,
                capabilities_added=parsed.capabilities_added,
                raw_message=parsed.raw_message,
                error=error,
            )

        return CodingWorkerExecution(
            status="failed",
            summary="",
            raw_message=stdout_text[: self.settings.coding_worker_max_message_chars],
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
        workspace_root: str | Path,
        add_dirs: tuple,
        schema_path: str | Path,
        last_message_path: str | Path,
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
