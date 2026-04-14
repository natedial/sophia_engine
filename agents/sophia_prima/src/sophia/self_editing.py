"""Gated self-edit proposal helpers for Sophia-owned guidance files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from difflib import unified_diff
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from sophia.config import Settings
from sophia.security.filesystem import ReadPolicy, WritePolicy


ProposalStatus = Literal["pending", "approved", "rejected", "promoted"]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SelfEditChangeRequest(BaseModel):
    """Requested replacement content for one target file."""

    model_config = ConfigDict(extra="forbid")

    target_path: str
    updated_content: str
    summary: str = ""


class SelfEditFileChange(BaseModel):
    """Durable record for one proposed file change."""

    model_config = ConfigDict(extra="forbid")

    target_path: str
    summary: str = ""
    existed_before: bool
    current_content_sha256: str
    proposed_content_sha256: str
    current_content: str
    proposed_content: str


class SelfEditProposal(BaseModel):
    """One durable proposal awaiting explicit human review."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    title: str
    rationale: str
    status: ProposalStatus = "pending"
    status_reason: str | None = None
    created_at: str
    updated_at: str
    source_agent_id: str | None = None
    source_run_id: str | None = None
    source_session_id: str | None = None
    review_actor: str | None = None
    review_timestamp: str | None = None
    promotion_branch: str | None = None
    promotion_commit: str | None = None
    patch_path: str
    changes: tuple[SelfEditFileChange, ...] = Field(default_factory=tuple)


class SelfEditProposalService:
    """Create, review, and promote gated self-edit proposals."""

    def __init__(
        self,
        *,
        settings: Settings,
        read_policy: ReadPolicy,
        write_policy: WritePolicy,
    ) -> None:
        self.settings = settings
        self.read_policy = read_policy
        self.write_policy = write_policy
        self.project_root = _resolve_project_root(settings)
        self.proposal_dir = self.settings.self_edit_proposal_dir.resolve(strict=False)
        self.allowed_globs = tuple(
            item.strip()
            for item in self.settings.self_edit_target_globs.split(",")
            if item.strip()
        )

    def create_proposal(
        self,
        *,
        title: str,
        rationale: str,
        changes: list[SelfEditChangeRequest],
        source_agent_id: str | None = None,
        source_run_id: str | None = None,
        source_session_id: str | None = None,
    ) -> SelfEditProposal:
        if not self.settings.self_edit_proposals_enabled:
            raise ValueError("Self-edit proposals are disabled by configuration.")
        normalized_title = title.strip()
        normalized_rationale = rationale.strip()
        if not normalized_title:
            raise ValueError("title cannot be empty")
        if not normalized_rationale:
            raise ValueError("rationale cannot be empty")
        if not changes:
            raise ValueError("at least one file change is required")

        proposal_changes: list[SelfEditFileChange] = []
        patch_parts: list[str] = []
        for request in changes:
            target_path = self._normalize_target_path(request.target_path)
            current_content = ""
            existed_before = target_path.exists()
            if existed_before:
                self.read_policy.ensure_allowed(target_path, purpose="self_edit_target")
                current_content = target_path.read_text(encoding="utf-8")
            elif not self.settings.self_edit_allow_new_files:
                raise ValueError(
                    f"self-edit target does not exist and new files are disabled: {request.target_path}"
                )

            if current_content == request.updated_content:
                continue

            patch_parts.extend(
                unified_diff(
                    current_content.splitlines(keepends=True),
                    request.updated_content.splitlines(keepends=True),
                    fromfile=target_path.relative_to(self.project_root).as_posix(),
                    tofile=target_path.relative_to(self.project_root).as_posix(),
                )
            )
            proposal_changes.append(
                SelfEditFileChange(
                    target_path=target_path.relative_to(self.project_root).as_posix(),
                    summary=request.summary.strip(),
                    existed_before=existed_before,
                    current_content_sha256=_sha256(current_content),
                    proposed_content_sha256=_sha256(request.updated_content),
                    current_content=current_content,
                    proposed_content=request.updated_content,
                )
            )

        if not proposal_changes:
            raise ValueError("proposal contains no actual file changes")

        proposal_id = _new_proposal_id()
        run_dir = self.proposal_dir / proposal_id
        self.write_policy.ensure_allowed(run_dir, purpose="self_edit_proposal_dir")
        run_dir.mkdir(parents=True, exist_ok=True)

        patch_path = run_dir / "proposal.patch"
        patch_path.write_text("".join(patch_parts), encoding="utf-8")

        now = _utc_now_iso()
        proposal = SelfEditProposal(
            proposal_id=proposal_id,
            title=normalized_title,
            rationale=normalized_rationale,
            created_at=now,
            updated_at=now,
            source_agent_id=source_agent_id,
            source_run_id=source_run_id,
            source_session_id=source_session_id,
            patch_path=str(patch_path),
            changes=tuple(proposal_changes),
        )
        self._write_proposal(proposal)
        return proposal

    def list_proposals(self) -> tuple[SelfEditProposal, ...]:
        if not self.proposal_dir.exists():
            return ()
        proposals: list[SelfEditProposal] = []
        for proposal_path in sorted(self.proposal_dir.glob("*/proposal.json")):
            proposals.append(SelfEditProposal.model_validate_json(proposal_path.read_text(encoding="utf-8")))
        proposals.sort(key=lambda item: item.created_at, reverse=True)
        return tuple(proposals)

    def load_proposal(self, proposal_id: str) -> SelfEditProposal:
        proposal_path = self.proposal_dir / proposal_id / "proposal.json"
        if not proposal_path.exists():
            raise FileNotFoundError(f"unknown self-edit proposal: {proposal_id}")
        return SelfEditProposal.model_validate_json(proposal_path.read_text(encoding="utf-8"))

    def review_proposal(
        self,
        *,
        proposal_id: str,
        status: Literal["approved", "rejected"],
        actor: str = "human",
        reason: str | None = None,
    ) -> SelfEditProposal:
        proposal = self.load_proposal(proposal_id)
        if proposal.status == "promoted":
            raise ValueError("promoted proposals cannot be reviewed again")
        now = _utc_now_iso()
        updated = proposal.model_copy(
            update={
                "status": status,
                "status_reason": (reason or "").strip() or None,
                "review_actor": actor.strip() or "human",
                "review_timestamp": now,
                "updated_at": now,
            }
        )
        self._write_proposal(updated)
        return updated

    def promote_to_branch(
        self,
        *,
        proposal_id: str,
        branch_name: str | None = None,
        commit_message: str | None = None,
    ) -> SelfEditProposal:
        proposal = self.load_proposal(proposal_id)
        if proposal.status != "approved":
            raise ValueError("proposal must be approved before promotion")
        repo_root = self._git_repo_root()
        if repo_root != self.project_root:
            raise ValueError(
                f"promotion repo root mismatch: expected {self.project_root}, got {repo_root}"
            )
        if self._has_unrelated_repo_changes():
            raise ValueError("promotion requires a clean git worktree")

        resolved_branch = _sanitize_branch_name(
            branch_name or f"sophia/self-edit-{proposal.proposal_id}"
        )
        if not resolved_branch:
            raise ValueError("branch_name resolved to an empty git ref")
        if self._git_output("rev-parse", "--verify", "--quiet", resolved_branch).strip():
            raise ValueError(f"git branch already exists: {resolved_branch}")

        self._git("switch", "-c", resolved_branch)
        for change in proposal.changes:
            target_path = (self.project_root / change.target_path).resolve(strict=False)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(change.proposed_content, encoding="utf-8")
        self._git("add", "--", *[change.target_path for change in proposal.changes])
        resolved_message = (commit_message or proposal.title).strip()
        if not resolved_message:
            resolved_message = f"Promote self-edit proposal {proposal.proposal_id}"
        self._git("commit", "-m", resolved_message)
        commit_hash = self._git_output("rev-parse", "HEAD").strip()

        updated = proposal.model_copy(
            update={
                "status": "promoted",
                "promotion_branch": resolved_branch,
                "promotion_commit": commit_hash,
                "updated_at": _utc_now_iso(),
            }
        )
        self._write_proposal(updated)
        return updated

    def _write_proposal(self, proposal: SelfEditProposal) -> Path:
        proposal_path = self.proposal_dir / proposal.proposal_id / "proposal.json"
        self.write_policy.ensure_allowed(proposal_path, purpose="self_edit_proposal")
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        proposal_path.write_text(
            json.dumps(proposal.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return proposal_path

    def _normalize_target_path(self, raw_path: str) -> Path:
        candidate = raw_path.strip()
        if not candidate:
            raise ValueError("target_path cannot be empty")
        raw = Path(candidate)
        if raw.is_absolute():
            raise ValueError("target_path must be project-relative, not absolute")
        normalized = (self.project_root / raw).resolve(strict=False)
        try:
            relative = normalized.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"target_path escapes the project root: {raw_path}") from exc
        relative_str = relative.as_posix()
        if not any(fnmatch(relative_str, pattern) for pattern in self.allowed_globs):
            raise ValueError(
                f"target_path is outside the self-edit allowlist: {relative_str}; "
                f"allowed={', '.join(self.allowed_globs) or '(none)'}"
            )
        return normalized

    def _git(self, *args: str) -> None:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "git command failed")

    def _git_output(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.project_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout

    def _git_repo_root(self) -> Path:
        output = self._git_output("rev-parse", "--show-toplevel").strip()
        if not output:
            raise ValueError("self-edit promotion requires a git repository")
        return Path(output).resolve(strict=False)

    def _has_unrelated_repo_changes(self) -> bool:
        ignored_prefix = self.proposal_dir.relative_to(self.project_root).as_posix().rstrip("/") + "/"
        for line in self._git_output("status", "--porcelain", "--untracked-files=all").splitlines():
            stripped = line.rstrip()
            if not stripped:
                continue
            path_text = stripped[3:] if len(stripped) > 3 else stripped
            if " -> " in path_text:
                path_text = path_text.split(" -> ", 1)[1]
            normalized = path_text.strip()
            if normalized == ignored_prefix.rstrip("/") or normalized.startswith(ignored_prefix):
                continue
            return True
        return False


def build_self_edit_service(
    *,
    settings: Settings,
    read_policy: ReadPolicy | None = None,
    write_policy: WritePolicy | None = None,
) -> SelfEditProposalService:
    """Construct the proposal service with resolved filesystem policies."""
    return SelfEditProposalService(
        settings=settings,
        read_policy=read_policy or settings.build_read_policy(),
        write_policy=write_policy or settings.build_write_policy(),
    )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _new_proposal_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{uuid4().hex[:8]}"


def _sanitize_branch_name(raw: str) -> str:
    collapsed = re.sub(r"[^A-Za-z0-9._/-]+", "-", raw.strip())
    collapsed = re.sub(r"-{2,}", "-", collapsed).strip("./-")
    return collapsed


def _resolve_project_root(settings: Settings) -> Path:
    candidates = [
        settings.personality_path.resolve(strict=False).parent.parent,
        settings.self_edit_proposal_dir.resolve(strict=False).parent.parent,
    ]
    if settings.skills_path:
        candidates.append(settings.skills_path.resolve(strict=False).parent)
    common = Path(os.path.commonpath([str(path) for path in candidates]))
    return common.resolve(strict=False)
