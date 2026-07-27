"""CLI for reviewing and promoting Sophia self-edit proposals."""

from __future__ import annotations

import argparse

from rich.console import Console
from rich.table import Table

from sophia.config import get_settings
from sophia.self_editing import build_self_edit_service


console = Console()


def main() -> None:
    """Entry point for self-edit proposal review commands."""
    parser = argparse.ArgumentParser(description="Review and promote Sophia self-edit proposals")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List self-edit proposals")

    show_parser = subparsers.add_parser("show", help="Show one self-edit proposal")
    show_parser.add_argument("proposal_id")

    approve_parser = subparsers.add_parser("approve", help="Approve a self-edit proposal")
    approve_parser.add_argument("proposal_id")
    approve_parser.add_argument("--actor", default="human")
    approve_parser.add_argument("--reason", default="")

    reject_parser = subparsers.add_parser("reject", help="Reject a self-edit proposal")
    reject_parser.add_argument("proposal_id")
    reject_parser.add_argument("--actor", default="human")
    reject_parser.add_argument("--reason", default="")

    promote_parser = subparsers.add_parser(
        "promote",
        help="Promote an approved self-edit proposal into a local git branch and commit",
    )
    promote_parser.add_argument("proposal_id")
    promote_parser.add_argument("--branch")
    promote_parser.add_argument("--commit-message")

    args = parser.parse_args()
    settings = get_settings()
    service = build_self_edit_service(settings=settings)

    if args.command == "list":
        proposals = service.list_proposals()
        if not proposals:
            console.print("No self-edit proposals found.")
            return
        table = Table(title="Self-Edit Proposals")
        table.add_column("Proposal ID")
        table.add_column("Status")
        table.add_column("Title")
        table.add_column("Updated")
        for proposal in proposals:
            table.add_row(
                proposal.proposal_id,
                proposal.status,
                proposal.title,
                proposal.updated_at,
            )
        console.print(table)
        return

    if args.command == "show":
        proposal = service.load_proposal(args.proposal_id)
        console.print(f"Proposal: {proposal.proposal_id}")
        console.print(f"Status: {proposal.status}")
        console.print(f"Title: {proposal.title}")
        console.print(f"Rationale: {proposal.rationale}")
        console.print(f"Patch: {proposal.patch_path}")
        if proposal.status_reason:
            console.print(f"Review note: {proposal.status_reason}")
        if proposal.promotion_branch:
            console.print(f"Promotion branch: {proposal.promotion_branch}")
        if proposal.promotion_commit:
            console.print(f"Promotion commit: {proposal.promotion_commit}")
        table = Table(title="Changes")
        table.add_column("Target")
        table.add_column("Summary")
        for change in proposal.changes:
            table.add_row(change.target_path, change.summary or "(no summary)")
        console.print(table)
        return

    if args.command == "approve":
        proposal = service.review_proposal(
            proposal_id=args.proposal_id,
            status="approved",
            actor=args.actor,
            reason=args.reason,
        )
        console.print(
            f"Approved {proposal.proposal_id}. Status={proposal.status}. Patch={proposal.patch_path}"
        )
        return

    if args.command == "reject":
        proposal = service.review_proposal(
            proposal_id=args.proposal_id,
            status="rejected",
            actor=args.actor,
            reason=args.reason,
        )
        console.print(f"Rejected {proposal.proposal_id}. Status={proposal.status}.")
        return

    if args.command == "promote":
        proposal = service.promote_to_branch(
            proposal_id=args.proposal_id,
            branch_name=args.branch,
            commit_message=args.commit_message,
        )
        console.print(
            "Promoted "
            f"{proposal.proposal_id} to branch {proposal.promotion_branch} at {proposal.promotion_commit}"
        )
        return

    raise AssertionError(f"Unhandled command: {args.command}")
