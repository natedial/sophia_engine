"""Git-host publishing abstractions for forge promotion flows."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from sophia_forge.config import ForgeSettings


@dataclass(frozen=True)
class PullRequestDraft:
    """Locally prepared draft PR payload."""

    repo_root: Path
    remote_url: str | None
    base_branch: str
    branch_name: str
    title: str
    body: str
    draft: bool
    commit_sha: str


@dataclass(frozen=True)
class PullRequestPublishResult:
    """Outcome of attempting to publish a PR or MR to a git host."""

    status: str
    provider: str
    message: str
    url: str | None = None
    external_id: str | None = None
    payload: dict[str, object] = field(default_factory=dict)


class GitHostPublisher(ABC):
    """Publish local promotion intent to a remote git host."""

    provider_name = "disabled"

    @abstractmethod
    def publish_pull_request(self, draft: PullRequestDraft) -> PullRequestPublishResult:
        """Attempt to publish a pull request or merge request."""


class DisabledGitHostPublisher(GitHostPublisher):
    """No-op publisher when host-side publication is not configured."""

    provider_name = "disabled"

    def publish_pull_request(self, draft: PullRequestDraft) -> PullRequestPublishResult:
        return PullRequestPublishResult(
            status="not_configured",
            provider=self.provider_name,
            message="Remote pull-request publication is not configured.",
        )


class GitHubGitHostPublisher(GitHostPublisher):
    """Publish PRs to GitHub using the REST API."""

    provider_name = "github"

    def __init__(self, settings: ForgeSettings) -> None:
        self.settings = settings

    def publish_pull_request(self, draft: PullRequestDraft) -> PullRequestPublishResult:
        token = os.environ.get(self.settings.github_token_env_var)
        if not token:
            return PullRequestPublishResult(
                status="not_configured",
                provider=self.provider_name,
                message=f"Missing GitHub token env var: {self.settings.github_token_env_var}",
            )
        repo_slug = _github_repo_slug(draft.remote_url)
        if repo_slug is None:
            return PullRequestPublishResult(
                status="not_configured",
                provider=self.provider_name,
                message="Could not derive GitHub repository slug from remote URL.",
                payload={"remote_url": draft.remote_url},
            )

        endpoint = (
            self.settings.github_api_base_url.rstrip("/")
            + f"/repos/{repo_slug}/pulls"
        )
        body = {
            "title": draft.title,
            "body": draft.body,
            "head": draft.branch_name,
            "base": draft.base_branch,
            "draft": draft.draft,
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "sophia-forge",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.git_host_request_timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return PullRequestPublishResult(
                status="failed",
                provider=self.provider_name,
                message=f"GitHub PR creation failed: {exc.code}",
                payload={"detail": exc.read().decode("utf-8", errors="replace")},
            )
        except Exception as exc:
            return PullRequestPublishResult(
                status="failed",
                provider=self.provider_name,
                message=f"GitHub PR creation failed: {exc}",
            )
        return PullRequestPublishResult(
            status="published",
            provider=self.provider_name,
            message="Published draft pull request to GitHub.",
            url=str(payload.get("html_url") or ""),
            external_id=str(payload.get("number") or ""),
            payload={"api_response": payload},
        )


class GitLabGitHostPublisher(GitHostPublisher):
    """Publish merge requests to GitLab using the REST API."""

    provider_name = "gitlab"

    def __init__(self, settings: ForgeSettings) -> None:
        self.settings = settings

    def publish_pull_request(self, draft: PullRequestDraft) -> PullRequestPublishResult:
        token = os.environ.get(self.settings.gitlab_token_env_var)
        if not token:
            return PullRequestPublishResult(
                status="not_configured",
                provider=self.provider_name,
                message=f"Missing GitLab token env var: {self.settings.gitlab_token_env_var}",
            )
        repo_slug = _gitlab_repo_slug(draft.remote_url)
        if repo_slug is None:
            return PullRequestPublishResult(
                status="not_configured",
                provider=self.provider_name,
                message="Could not derive GitLab project path from remote URL.",
                payload={"remote_url": draft.remote_url},
            )

        project = urllib.parse.quote(repo_slug, safe="")
        endpoint = (
            self.settings.gitlab_api_base_url.rstrip("/")
            + f"/projects/{project}/merge_requests"
        )
        body = {
            "source_branch": draft.branch_name,
            "target_branch": draft.base_branch,
            "title": draft.title if not draft.draft else f"Draft: {draft.title}",
            "description": draft.body,
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "PRIVATE-TOKEN": token,
                "Content-Type": "application/json",
                "User-Agent": "sophia-forge",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.git_host_request_timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return PullRequestPublishResult(
                status="failed",
                provider=self.provider_name,
                message=f"GitLab MR creation failed: {exc.code}",
                payload={"detail": exc.read().decode("utf-8", errors="replace")},
            )
        except Exception as exc:
            return PullRequestPublishResult(
                status="failed",
                provider=self.provider_name,
                message=f"GitLab MR creation failed: {exc}",
            )
        return PullRequestPublishResult(
            status="published",
            provider=self.provider_name,
            message="Published draft merge request to GitLab.",
            url=str(payload.get("web_url") or ""),
            external_id=str(payload.get("iid") or ""),
            payload={"api_response": payload},
        )


def build_git_host_publisher(settings: ForgeSettings) -> GitHostPublisher:
    if settings.git_host_provider == "github":
        return GitHubGitHostPublisher(settings)
    if settings.git_host_provider == "gitlab":
        return GitLabGitHostPublisher(settings)
    return DisabledGitHostPublisher()


def _github_repo_slug(remote_url: str | None) -> str | None:
    return _normalize_repo_slug(remote_url, host_hint="github.com")


def _gitlab_repo_slug(remote_url: str | None) -> str | None:
    return _normalize_repo_slug(remote_url, host_hint="gitlab")


def _normalize_repo_slug(remote_url: str | None, *, host_hint: str) -> str | None:
    if not remote_url:
        return None
    text = remote_url.strip()
    if not text:
        return None

    if text.startswith("git@"):
        _, _, remainder = text.partition(":")
        candidate = remainder
    elif "://" in text:
        parsed = urllib.parse.urlparse(text)
        if host_hint not in (parsed.hostname or ""):
            return None
        candidate = parsed.path.lstrip("/")
    else:
        return None

    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    candidate = candidate.strip("/")
    return candidate or None
