"""Codex-backed delegated development worker."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from sophia.config import Settings
from sophia.security.filesystem import ReadPolicy, WritePolicy


ProcessFactory = Callable[..., Awaitable[asyncio.subprocess.Process]]


@dataclass(frozen=True)
class DevWorkerExecution:
    """Structured result returned by the Codex-backed dev worker."""

    success: bool
    status: str
    summary: str
    changed_files: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    follow_ups: tuple[str, ...] = ()
    raw_message: str = ""
    error: str | None = None


class CodexDevWorker:
    """Run Codex CLI in a bounded workspace for implementation tasks."""

    def __init__(
        self,
        *,
        settings: Settings,
        read_policy: ReadPolicy,
        write_policy: WritePolicy,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self.settings = settings
        self.read_policy = read_policy
        self.write_policy = write_policy
        self.process_factory = process_factory or asyncio.create_subprocess_exec

    async def run(
        self,
        *,
        supervisor_task: str,
        task_id: str,
        timeout_sec: float,
    ) -> DevWorkerExecution:
        if not self.settings.dev_worker_enabled:
            return DevWorkerExecution(
                success=False,
                status="disabled",
                summary="",
                error="dev_worker is disabled by configuration",
            )

        codex_bin = self.settings.dev_worker_codex_command.strip() or "codex"
        resolved_bin = shutil.which(codex_bin)
        if resolved_bin is None:
            return DevWorkerExecution(
                success=False,
                status="unavailable",
                summary="",
                error=f"Codex CLI not found on PATH: {codex_bin}",
            )

        workspace_root = self.settings.dev_worker_workspace_root.resolve(strict=False)
        self.read_policy.ensure_allowed(workspace_root, purpose="dev_worker_workspace_root")
        self.write_policy.ensure_allowed(workspace_root, purpose="dev_worker_workspace_root")

        output_dir = self.settings.dev_worker_output_dir.resolve(strict=False)
        self.write_policy.ensure_allowed(output_dir, purpose="dev_worker_output_dir")
        output_dir.mkdir(parents=True, exist_ok=True)

        schema_path = output_dir / f"{task_id}_schema.json"
        last_message_path = output_dir / f"{task_id}_last_message.json"
        schema_path.write_text(json.dumps(_output_schema(), indent=2), encoding="utf-8")
        if last_message_path.exists():
            last_message_path.unlink()

        add_dirs = self._build_add_dirs(workspace_root)
        prompt = self._build_prompt(
            supervisor_task=supervisor_task,
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
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
        except TimeoutError:
            return DevWorkerExecution(
                success=False,
                status="timed_out",
                summary="",
                error="Codex dev worker timed out",
            )
        except PermissionError as exc:
            return DevWorkerExecution(
                success=False,
                status="permission_denied",
                summary="",
                error=str(exc),
            )
        except Exception as exc:
            return DevWorkerExecution(
                success=False,
                status="failed",
                summary="",
                error=f"Codex dev worker launch failed: {exc}",
            )

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        parsed = self._parse_last_message(last_message_path)
        if parsed is not None:
            success = process.returncode == 0 and parsed.status == "completed"
            error = None
            if process.returncode != 0:
                error = self._format_failure(
                    return_code=process.returncode,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                )
            elif not success:
                error = parsed.error or f"Codex finished with status={parsed.status}"
            return DevWorkerExecution(
                success=success,
                status=parsed.status,
                summary=parsed.summary,
                changed_files=parsed.changed_files,
                verification=parsed.verification,
                follow_ups=parsed.follow_ups,
                raw_message=parsed.raw_message,
                error=error,
            )

        error = self._format_failure(
            return_code=process.returncode,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
        )
        return DevWorkerExecution(
            success=False,
            status="failed",
            summary="",
            raw_message=stdout_text,
            error=error,
        )

    def _build_add_dirs(self, workspace_root: Path) -> tuple[Path, ...]:
        add_dirs: list[Path] = []
        for root in self.write_policy.allowed_roots:
            resolved = root.resolve(strict=False)
            if resolved == workspace_root:
                continue
            if _is_within(resolved, workspace_root):
                continue
            add_dirs.append(resolved)
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in add_dirs:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return tuple(deduped)

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
            self.settings.dev_worker_codex_sandbox,
            "-C",
            str(workspace_root),
            "--output-schema",
            str(schema_path),
            "-o",
            str(last_message_path),
        ]
        if self.settings.dev_worker_model.strip():
            command.extend(["-m", self.settings.dev_worker_model.strip()])
        for add_dir in add_dirs:
            command.extend(["--add-dir", str(add_dir)])
        command.append(prompt)
        return command

    def _build_prompt(
        self,
        *,
        supervisor_task: str,
        workspace_root: Path,
        add_dirs: tuple[Path, ...],
    ) -> str:
        writable_scope = [str(workspace_root), *[str(path) for path in add_dirs]]
        writable_scope_text = ", ".join(writable_scope) if writable_scope else "(none)"
        return (
            "You are Sophia's delegated development worker.\n"
            "Inspect the local repository, plan the smallest durable implementation, "
            "and execute it inside the Codex sandbox.\n"
            "Constraints:\n"
            "- Work only inside the allowed writable scope.\n"
            "- Prefer minimal, production-appropriate changes over broad refactors.\n"
            "- Run targeted verification when practical.\n"
            "- If blocked, explain the blocker precisely.\n"
            "- Final output must satisfy the provided JSON schema.\n"
            f"Primary workspace root: {workspace_root}\n"
            f"Writable scope: {writable_scope_text}\n"
            "Supervisor task:\n"
            f"{supervisor_task.strip()}"
        )

    def _parse_last_message(self, last_message_path: Path) -> DevWorkerExecution | None:
        if not last_message_path.exists():
            return None
        raw = last_message_path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return DevWorkerExecution(
                success=False,
                status="invalid_output",
                summary=raw[: self.settings.dev_worker_max_message_chars],
                raw_message=raw,
                error="Codex dev worker returned non-JSON output",
            )

        if not isinstance(payload, dict):
            return DevWorkerExecution(
                success=False,
                status="invalid_output",
                summary=raw[: self.settings.dev_worker_max_message_chars],
                raw_message=raw,
                error="Codex dev worker output schema root must be an object",
            )

        status = str(payload.get("status") or "failed").strip() or "failed"
        summary = str(payload.get("summary") or "").strip()
        changed_files = _coerce_str_list(payload.get("changed_files"))
        verification = _coerce_str_list(payload.get("verification"))
        follow_ups = _coerce_str_list(payload.get("follow_ups"))
        return DevWorkerExecution(
            success=status == "completed",
            status=status,
            summary=summary[: self.settings.dev_worker_max_message_chars],
            changed_files=tuple(changed_files),
            verification=tuple(verification),
            follow_ups=tuple(follow_ups),
            raw_message=raw[: self.settings.dev_worker_max_message_chars],
            error=None if status == "completed" else f"Codex finished with status={status}",
        )

    @staticmethod
    def _format_failure(
        *,
        return_code: int,
        stdout_text: str,
        stderr_text: str,
    ) -> str:
        stderr_clean = stderr_text.strip()
        stdout_clean = stdout_text.strip()
        detail = stderr_clean or stdout_clean or "No diagnostic output captured"
        if len(detail) > 800:
            detail = f"{detail[:800].rstrip()}..."
        return f"Codex exec failed with exit code {return_code}: {detail}"


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {
                "type": "string",
                "enum": ["completed", "blocked", "failed"],
            },
            "summary": {"type": "string"},
            "changed_files": {
                "type": "array",
                "items": {"type": "string"},
            },
            "verification": {
                "type": "array",
                "items": {"type": "string"},
            },
            "follow_ups": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "status",
            "summary",
            "changed_files",
            "verification",
            "follow_ups",
        ],
    }
