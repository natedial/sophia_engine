"""Promotion helpers for forge runs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from sophia_forge.core.artifacts import ArtifactManager
from sophia_forge.core.git_host import (
    GitHostPublisher,
    PullRequestDraft,
    PullRequestPublishResult,
    build_git_host_publisher,
)
from sophia_forge.core.outcomes import required_verification_passed
from sophia_forge.config import ForgeSettings
from sophia_forge_protocol.artifact_models import RunArtifact
from sophia_forge_protocol.run_models import RunRequest, RunResult
from sophia_forge_protocol.verification_models import VerificationResult


@dataclass(frozen=True)
class PromotionOutcome:
    """Result of applying a promotion policy after a forge run."""

    mode: str
    status: str
    message: str
    artifacts: tuple[RunArtifact, ...] = ()
    payload: dict[str, object] = field(default_factory=dict)


class PromotionManager:
    """Create post-verification promotion artifacts for forge runs."""

    def __init__(
        self,
        artifact_manager: ArtifactManager,
        *,
        settings: ForgeSettings | None = None,
        git_host_publisher: GitHostPublisher | None = None,
    ) -> None:
        self.artifact_manager = artifact_manager
        self.settings = settings or artifact_manager.settings
        self.git_host_publisher = git_host_publisher or build_git_host_publisher(self.settings)

    def promote(
        self,
        *,
        request: RunRequest,
        result: RunResult,
        verification_results: tuple[VerificationResult, ...],
    ) -> PromotionOutcome:
        run_id = request.run_id or "forge_run"
        policy = request.promotion_policy
        mode = policy.mode
        verification_pass = required_verification_passed(verification_results)

        if result.status != "completed":
            return self._persist_status(
                run_id=run_id,
                mode=mode,
                status="skipped",
                message="Promotion skipped because the run did not complete successfully.",
                extra_payload={"run_status": result.status},
            )

        if mode in {"inherit", "none"}:
            return self._persist_status(
                run_id=run_id,
                mode=mode,
                status="skipped",
                message="Promotion mode did not request a post-run delivery action.",
                extra_payload={"run_status": result.status},
            )

        if policy.require_verification_pass and verification_pass is False:
            return self._persist_status(
                run_id=run_id,
                mode=mode,
                status="blocked",
                message="Promotion blocked because required verification did not pass.",
                extra_payload={"verification_passed": False},
            )

        if mode == "patch":
            return self._create_patch_promotion(
                run_id=run_id,
                request=request,
                result=result,
                verification_pass=verification_pass,
            )

        if mode == "draft_pr":
            return self._create_draft_pr_promotion(
                run_id=run_id,
                request=request,
                result=result,
                verification_pass=verification_pass,
            )

        if mode not in {"patch", "draft_pr"}:
            return self._persist_status(
                run_id=run_id,
                mode=mode,
                status="blocked",
                message=f"Promotion mode is not implemented yet: {mode}",
                extra_payload={"implemented_modes": ["patch", "draft_pr"]},
            )
        raise AssertionError(f"unhandled promotion mode: {mode}")

    def _create_patch_promotion(
        self,
        *,
        run_id: str,
        request: RunRequest,
        result: RunResult,
        verification_pass: bool | None,
    ) -> PromotionOutcome:
        workspace_root = Path(request.workspace_root).expanduser().resolve(strict=False)
        repo_root = _find_repo_root(workspace_root)
        if repo_root is None:
            return self._persist_status(
                run_id=run_id,
                mode="patch",
                status="blocked",
                message="Patch promotion requires a git repository workspace.",
                extra_payload={"workspace_root": str(workspace_root)},
            )

        changed_paths = _resolve_changed_paths(
            repo_root=repo_root,
            workspace_root=workspace_root,
            changed_files=result.changed_files,
        )
        if not changed_paths:
            return self._persist_status(
                run_id=run_id,
                mode="patch",
                status="skipped",
                message="Patch promotion skipped because no repo-relative changed files were reported.",
                extra_payload={"changed_files": list(result.changed_files)},
            )

        try:
            patch_text = _build_patch(repo_root=repo_root, changed_paths=changed_paths)
        except Exception as exc:
            return self._persist_status(
                run_id=run_id,
                mode="patch",
                status="failed",
                message=f"Patch promotion failed: {exc}",
                extra_payload={"repo_root": str(repo_root)},
            )

        if not patch_text.strip():
            return self._persist_status(
                run_id=run_id,
                mode="patch",
                status="skipped",
                message="Patch promotion skipped because git diff produced no patch.",
                extra_payload={
                    "repo_root": str(repo_root),
                    "changed_files": [path.as_posix() for path in changed_paths],
                },
            )

        patch_artifact = self.artifact_manager.persist_patch_artifact(
            run_id=run_id,
            patch_text=patch_text,
            payload={
                "mode": "patch",
                "repo_root": str(repo_root),
                "changed_files": [path.as_posix() for path in changed_paths],
            },
        )
        status_outcome = self._persist_status(
            run_id=run_id,
            mode="patch",
            status="created",
            message="Created a patch artifact for the verified change set.",
            extra_payload={
                "repo_root": str(repo_root),
                "verification_passed": verification_pass,
                "changed_files": [path.as_posix() for path in changed_paths],
                "patch_artifact_id": patch_artifact.artifact_id,
            },
        )
        return PromotionOutcome(
            mode="patch",
            status="created",
            message="Created a patch artifact for the verified change set.",
            artifacts=(status_outcome.artifacts[0], patch_artifact),
            payload={
                **status_outcome.payload,
                "patch_artifact_id": patch_artifact.artifact_id,
            },
        )

    def _create_draft_pr_promotion(
        self,
        *,
        run_id: str,
        request: RunRequest,
        result: RunResult,
        verification_pass: bool | None,
    ) -> PromotionOutcome:
        workspace_root = Path(request.workspace_root).expanduser().resolve(strict=False)
        repo_root = _find_repo_root(workspace_root)
        if repo_root is None:
            return self._persist_status(
                run_id=run_id,
                mode="draft_pr",
                status="blocked",
                message="Draft PR promotion requires a git repository workspace.",
                extra_payload={"workspace_root": str(workspace_root)},
            )

        changed_paths = _resolve_changed_paths(
            repo_root=repo_root,
            workspace_root=workspace_root,
            changed_files=result.changed_files,
        )
        if not changed_paths:
            return self._persist_status(
                run_id=run_id,
                mode="draft_pr",
                status="skipped",
                message="Draft PR promotion skipped because no repo-relative changed files were reported.",
                extra_payload={"changed_files": list(result.changed_files)},
            )

        unrelated_changes = _unrelated_status_entries(
            repo_root=repo_root, changed_paths=changed_paths
        )
        if unrelated_changes:
            return self._persist_status(
                run_id=run_id,
                mode="draft_pr",
                status="blocked",
                message="Draft PR promotion requires a clean repo outside Forge-managed changed files.",
                extra_payload={"unrelated_changes": unrelated_changes},
            )

        policy = request.promotion_policy
        branch_name = (policy.branch_name or f"forge/{_sanitize_ref_component(run_id)}").strip()
        if not branch_name:
            branch_name = f"forge/{_sanitize_ref_component(run_id)}"
        existing_branch = _git_output(repo_root, "rev-parse", "--verify", "--quiet", branch_name)
        if existing_branch:
            return self._persist_status(
                run_id=run_id,
                mode="draft_pr",
                status="blocked",
                message=f"Draft PR branch already exists locally: {branch_name}",
                extra_payload={"branch_name": branch_name},
            )

        current_branch = _git_output(repo_root, "branch", "--show-current").strip()
        base_branch = (policy.base_branch or current_branch).strip()
        if not base_branch:
            return self._persist_status(
                run_id=run_id,
                mode="draft_pr",
                status="blocked",
                message="Draft PR promotion requires a base_branch when the repository is detached.",
            )

        commit_message = (policy.commit_message or "").strip() or (
            result.summary.strip() if result.summary.strip() else f"Forge update for {run_id}"
        )
        pr_title = ((policy.pr_title or "").strip() or commit_message).strip()
        pr_body = (policy.pr_body or "").strip() or _default_pr_body(
            run_id=run_id, result=result, verification_pass=verification_pass
        )

        try:
            _git_run(repo_root, "switch", "-c", branch_name)
            _git_run(repo_root, "add", "--", *[path.as_posix() for path in changed_paths])
            _git_run(
                repo_root,
                "-c",
                f"user.name={self.settings.git_author_name}",
                "-c",
                f"user.email={self.settings.git_author_email}",
                "commit",
                "-m",
                commit_message,
                "--no-verify",
            )
            commit_sha = _git_output(repo_root, "rev-parse", "HEAD").strip()
        except Exception as exc:
            return self._persist_status(
                run_id=run_id,
                mode="draft_pr",
                status="failed",
                message=f"Draft PR local branch preparation failed: {exc}",
                extra_payload={"branch_name": branch_name},
            )

        remote_url = (
            _git_output(repo_root, "remote", "get-url", self.settings.git_remote_name).strip()
            or None
        )
        draft = PullRequestDraft(
            repo_root=repo_root,
            remote_url=remote_url,
            base_branch=base_branch,
            branch_name=branch_name,
            title=pr_title,
            body=pr_body,
            draft=policy.draft,
            commit_sha=commit_sha,
        )
        if self.git_host_publisher.provider_name != "disabled":
            if not remote_url:
                publish_result = PullRequestPublishResult(
                    status="not_configured",
                    provider=self.git_host_publisher.provider_name,
                    message="Configured git-host publication requires a remote URL.",
                )
            else:
                try:
                    _git_run(repo_root, "push", "-u", self.settings.git_remote_name, branch_name)
                    publish_result = self.git_host_publisher.publish_pull_request(draft)
                except Exception as exc:
                    publish_result = PullRequestPublishResult(
                        status="failed",
                        provider=self.git_host_publisher.provider_name,
                        message=f"Failed to push branch before PR publication: {exc}",
                    )
        else:
            publish_result = self.git_host_publisher.publish_pull_request(draft)
        pr_request_artifact = self.artifact_manager.persist_pr_request(
            run_id=run_id,
            payload={
                "run_id": run_id,
                "mode": "draft_pr",
                "repo_root": str(repo_root),
                "remote_url": remote_url,
                "base_branch": base_branch,
                "branch_name": branch_name,
                "commit_message": commit_message,
                "pr_title": pr_title,
                "pr_body": pr_body,
                "draft": policy.draft,
                "commit_sha": commit_sha,
                "provider": publish_result.provider,
                "publish_status": publish_result.status,
                "publish_url": publish_result.url,
                "publish_message": publish_result.message,
                "publish_external_id": publish_result.external_id,
                "changed_files": [path.as_posix() for path in changed_paths],
            },
        )
        if publish_result.status == "published":
            status = "published"
            message = "Prepared a local branch and published a draft pull request."
        elif publish_result.status == "not_configured":
            status = "prepared"
            message = "Prepared a local branch and PR request artifact, but remote publication is not configured."
        else:
            status = "failed"
            message = (
                f"Prepared a local branch, but remote publication failed: {publish_result.message}"
            )
        status_outcome = self._persist_status(
            run_id=run_id,
            mode="draft_pr",
            status=status,
            message=message,
            extra_payload={
                "repo_root": str(repo_root),
                "base_branch": base_branch,
                "branch_name": branch_name,
                "commit_sha": commit_sha,
                "verification_passed": verification_pass,
                "provider": publish_result.provider,
                "publish_status": publish_result.status,
                "publish_url": publish_result.url,
                "publish_external_id": publish_result.external_id,
                "pr_request_artifact_id": pr_request_artifact.artifact_id,
            },
        )
        return PromotionOutcome(
            mode="draft_pr",
            status=status,
            message=message,
            artifacts=(status_outcome.artifacts[0], pr_request_artifact),
            payload={
                **status_outcome.payload,
                "pr_request_artifact_id": pr_request_artifact.artifact_id,
            },
        )

    def publish_prepared_pr(
        self,
        *,
        run_id: str,
        pr_request_path: Path,
        promotion_status_path: Path | None = None,
    ) -> PromotionOutcome:
        if not pr_request_path.exists():
            return PromotionOutcome(
                mode="draft_pr",
                status="failed",
                message="PR request artifact file not found.",
            )

        payload = json.loads(pr_request_path.read_text(encoding="utf-8"))
        mode = str(payload.get("mode") or "")
        if mode != "draft_pr":
            return PromotionOutcome(
                mode=mode or "unknown",
                status="blocked",
                message="Only draft_pr promotions can be published.",
                payload=payload,
            )

        current_publish_status = str(payload.get("publish_status") or "")
        if current_publish_status == "published":
            return PromotionOutcome(
                mode="draft_pr",
                status="published",
                message="Pull request is already published.",
                payload=payload,
            )

        repo_root_text = str(payload.get("repo_root") or "").strip()
        branch_name = str(payload.get("branch_name") or "").strip()
        base_branch = str(payload.get("base_branch") or "").strip()
        title = str(payload.get("pr_title") or "").strip()
        body = str(payload.get("pr_body") or "").strip()
        commit_sha = str(payload.get("commit_sha") or "").strip()
        remote_url = str(payload.get("remote_url") or "").strip() or None
        draft = bool(payload.get("draft", True))
        if not repo_root_text or not branch_name or not base_branch or not title:
            return PromotionOutcome(
                mode="draft_pr",
                status="failed",
                message="Draft PR artifact is missing required publication fields.",
                payload=payload,
            )

        repo_root = Path(repo_root_text).expanduser().resolve(strict=False)
        draft_request = PullRequestDraft(
            repo_root=repo_root,
            remote_url=remote_url,
            base_branch=base_branch,
            branch_name=branch_name,
            title=title,
            body=body,
            draft=draft,
            commit_sha=commit_sha,
        )

        if self.git_host_publisher.provider_name != "disabled":
            if not remote_url:
                publish_result = PullRequestPublishResult(
                    status="not_configured",
                    provider=self.git_host_publisher.provider_name,
                    message="Configured git-host publication requires a remote URL.",
                )
            else:
                try:
                    current_commit = _git_run(repo_root, "rev-parse", branch_name).strip()
                    if current_commit != commit_sha:
                        return PromotionOutcome(
                            mode="draft_pr",
                            status="failed",
                            message=(
                                f"Branch '{branch_name}' HEAD ({current_commit[:7]}) does not "
                                f"match the reviewed artifact's commit ({commit_sha[:7]}). "
                                "The branch has changed since the draft was created. "
                                "Please recreate the draft from current HEAD or reset the branch."
                            ),
                            payload=payload,
                        )
                    _git_run(repo_root, "push", "-u", self.settings.git_remote_name, branch_name)
                    publish_result = self.git_host_publisher.publish_pull_request(draft_request)
                except Exception as exc:
                    publish_result = PullRequestPublishResult(
                        status="failed",
                        provider=self.git_host_publisher.provider_name,
                        message=f"Failed to push branch before PR publication: {exc}",
                    )
        else:
            publish_result = self.git_host_publisher.publish_pull_request(draft_request)

        updated_payload = {
            **payload,
            "provider": publish_result.provider,
            "publish_status": publish_result.status,
            "publish_url": publish_result.url,
            "publish_message": publish_result.message,
            "publish_external_id": publish_result.external_id,
        }
        pr_request_path.write_text(
            json.dumps(updated_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        if publish_result.status == "published":
            status = "published"
            message = "Published draft pull request."
        elif publish_result.status == "not_configured":
            status = "prepared"
            message = "Draft PR is prepared locally, but remote publication is not configured."
        else:
            status = "failed"
            message = f"Draft PR publication failed: {publish_result.message}"

        status_payload = {
            "run_id": run_id,
            "mode": "draft_pr",
            "status": status,
            "message": message,
            "repo_root": str(repo_root),
            "base_branch": base_branch,
            "branch_name": branch_name,
            "commit_sha": commit_sha,
            "provider": publish_result.provider,
            "publish_status": publish_result.status,
            "publish_url": publish_result.url,
            "publish_external_id": publish_result.external_id,
            "pr_request_artifact_path": str(pr_request_path),
        }
        if promotion_status_path is not None:
            promotion_status_path.parent.mkdir(parents=True, exist_ok=True)
            promotion_status_path.write_text(
                json.dumps(status_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

        return PromotionOutcome(
            mode="draft_pr",
            status=status,
            message=message,
            payload=status_payload,
        )

    def _persist_status(
        self,
        *,
        run_id: str,
        mode: str,
        status: str,
        message: str,
        extra_payload: dict[str, object] | None = None,
    ) -> PromotionOutcome:
        payload = {
            "run_id": run_id,
            "mode": mode,
            "status": status,
            "message": message,
            **(extra_payload or {}),
        }
        artifact = self.artifact_manager.persist_promotion_status(run_id=run_id, payload=payload)
        return PromotionOutcome(
            mode=mode,
            status=status,
            message=message,
            artifacts=(artifact,),
            payload=payload,
        )


def _find_repo_root(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _resolve_changed_paths(
    *,
    repo_root: Path,
    workspace_root: Path,
    changed_files: tuple[str, ...],
) -> tuple[Path, ...]:
    resolved: list[Path] = []
    seen: set[str] = set()
    for item in changed_files:
        candidate = Path(item)
        candidate_path = None
        if candidate.is_absolute():
            if _is_within(candidate, repo_root):
                candidate_path = candidate.relative_to(repo_root)
        else:
            workspace_candidate = (workspace_root / candidate).resolve(strict=False)
            repo_candidate = (repo_root / candidate).resolve(strict=False)
            if _is_within(workspace_candidate, repo_root):
                candidate_path = workspace_candidate.relative_to(repo_root)
            elif _is_within(repo_candidate, repo_root):
                candidate_path = repo_candidate.relative_to(repo_root)
        if candidate_path is None:
            continue
        normalized = Path(candidate_path.as_posix())
        key = normalized.as_posix()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(normalized)
    return tuple(resolved)


def _unrelated_status_entries(*, repo_root: Path, changed_paths: tuple[Path, ...]) -> list[str]:
    allowed = {path.as_posix() for path in changed_paths}
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    )
    unrelated: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path_text = line[3:].strip()
        normalized = path_text
        if " -> " in normalized:
            normalized = normalized.split(" -> ", 1)[1].strip()
        if normalized not in allowed:
            unrelated.append(line.strip())
    return unrelated


def _build_patch(*, repo_root: Path, changed_paths: tuple[Path, ...]) -> str:
    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff",
            "--binary",
            "--relative",
            "HEAD",
            "--",
            *[path.as_posix() for path in changed_paths],
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    patch_parts = [tracked.stdout.strip()]

    untracked = _list_untracked_paths(repo_root=repo_root)
    for path in changed_paths:
        if path.as_posix() not in untracked:
            continue
        created = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "diff",
                "--binary",
                "--no-index",
                "--",
                "/dev/null",
                str(repo_root / path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode not in {0, 1}:
            raise RuntimeError(created.stderr.strip() or f"git diff --no-index failed for {path}")
        text = created.stdout.replace(f"b/{(repo_root / path).as_posix()}", f"b/{path.as_posix()}")
        text = text.replace(f"+++ {(repo_root / path).as_posix()}", f"+++ b/{path.as_posix()}")
        patch_parts.append(text.strip())

    return "\n\n".join(part for part in patch_parts if part).strip() + "\n"


def _list_untracked_paths(*, repo_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _git_run(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _git_output(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def _sanitize_ref_component(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned or "run"


def _default_pr_body(*, run_id: str, result: RunResult, verification_pass: bool | None) -> str:
    lines = [f"Forge run: {run_id}"]
    if result.summary.strip():
        lines.append("")
        lines.append(result.summary.strip())
    if result.changed_files:
        lines.append("")
        lines.append("Changed files:")
        lines.extend(f"- {path}" for path in result.changed_files[:12])
    if verification_pass is not None:
        lines.append("")
        lines.append(f"Required verification passed: {verification_pass}")
    return "\n".join(lines).strip()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
