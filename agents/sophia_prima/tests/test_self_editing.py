from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sophia.agent_local_tools import AgentLocalTools
from sophia.config import Settings
from sophia.memory import MemoryManager, MemoryManagerConfig
from sophia.memory.store import InMemoryMemoryStore
from sophia.self_editing import SelfEditChangeRequest, build_self_edit_service


def _build_settings(tmp_path: Path) -> Settings:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "personality.md").write_text("# Sophia\n\n## Style\nPlain.", encoding="utf-8")
    (config_dir / "soul.md").write_text("Soul text", encoding="utf-8")
    (config_dir / "LESSONS.md").write_text("- Verify dates.\n", encoding="utf-8")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    writable_dir = tmp_path / ".sophia"
    writable_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        personality_path=config_dir / "personality.md",
        soul_path=config_dir / "soul.md",
        lessons_path=config_dir / "LESSONS.md",
        skills_path=skills_dir,
        self_edit_proposal_dir=writable_dir / "self_edit_proposals",
        agent_fs_read_allowlist=",".join(
            [
                str(config_dir),
                str(skills_dir),
                str(writable_dir),
            ]
        ),
        agent_fs_write_allowlist=str(writable_dir),
    )


def test_self_edit_proposal_writes_pending_artifacts(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    service = build_self_edit_service(settings=settings)
    proposal = service.create_proposal(
        title="Tighten formatting policy",
        rationale="Prefer tighter answers for quick-turn chats.",
        changes=[
            SelfEditChangeRequest(
                target_path="config/personality.md",
                updated_content="# Sophia\n\n## Style\nTighter.",
                summary="Tighten the style note.",
            )
        ],
        source_agent_id="sophia_prima",
        source_run_id="run-123",
        source_session_id="session-123",
    )

    assert proposal.status == "pending"
    assert proposal.source_run_id == "run-123"
    assert Path(proposal.patch_path).exists()
    patch_text = Path(proposal.patch_path).read_text(encoding="utf-8")
    assert "--- config/personality.md" in patch_text
    loaded = service.load_proposal(proposal.proposal_id)
    assert loaded.title == "Tighten formatting policy"
    assert loaded.changes[0].target_path == "config/personality.md"


def test_self_edit_proposal_rejects_targets_outside_allowlist(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    service = build_self_edit_service(settings=settings)

    with pytest.raises(ValueError, match="outside the self-edit allowlist"):
        service.create_proposal(
            title="Bad target",
            rationale="Should fail.",
            changes=[
                SelfEditChangeRequest(
                    target_path="README.md",
                    updated_content="not allowed",
                )
            ],
        )


def test_promote_approved_self_edit_creates_branch_and_commit(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Sophia Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "sophia@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=tmp_path, check=True)

    service = build_self_edit_service(settings=settings)
    proposal = service.create_proposal(
        title="Refine personality wording",
        rationale="Clarify the style section.",
        changes=[
            SelfEditChangeRequest(
                target_path="config/personality.md",
                updated_content="# Sophia\n\n## Style\nVery precise.",
                summary="Refine style wording.",
            )
        ],
    )
    service.review_proposal(
        proposal_id=proposal.proposal_id,
        status="approved",
        actor="tester",
        reason="Looks good.",
    )

    promoted = service.promote_to_branch(
        proposal_id=proposal.proposal_id,
        branch_name="sophia/self-edit-test",
        commit_message="Promote approved self-edit",
    )

    head_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_branch == "sophia/self-edit-test"
    assert promoted.status == "promoted"
    assert promoted.promotion_branch == "sophia/self-edit-test"
    assert promoted.promotion_commit
    assert (tmp_path / "config" / "personality.md").read_text(encoding="utf-8").endswith(
        "Very precise."
    )


def test_agent_local_tool_creates_self_edit_proposal(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    tools = AgentLocalTools(
        MemoryManager(store=InMemoryMemoryStore(), config=MemoryManagerConfig()),
        settings=settings,
        read_policy=settings.build_read_policy(),
        write_policy=settings.build_write_policy(),
    )

    result = tools.propose_self_edit(
        title="Update lesson seed",
        rationale="Add a more explicit verification rule.",
        changes=[
            {
                "target_path": "config/LESSONS.md",
                "updated_content": "- Verify dates.\n- State data sources.\n",
                "summary": "Add a sourcing reminder.",
            }
        ],
    )

    assert "Created self-edit proposal" in result
    assert "human approval is required" in result
