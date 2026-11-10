"""CLI for the scripted outside research agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from outside_research_agent.analyst import (
    AnalystSurfaceError,
    extract_claims,
    load_analyst_payload,
)
from outside_research_agent.sophia import SophiaCli, SophiaProtocolError
from outside_research_agent.workflow import resume_case, run_case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="outside-research-agent",
        description=(
            "Coordinate Analyst public claims and Sophia research cases. "
            "Does not embed a research agenda in Sophia."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Open a case from Analyst or generic claims")
    _add_sophia_args(run_parser)
    run_parser.add_argument("--actor", default="agent-a")
    source = run_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--analyst-json", type=Path, help="Analyst public JSON payload")
    source.add_argument("--generic-json", type=Path, help="Already-generic source-claim bundle")
    run_parser.add_argument("--observations-json", type=Path)

    resume_parser = sub.add_parser("resume", help="Resume a case from IDs only")
    _add_sophia_args(resume_parser)
    resume_parser.add_argument("--case-id", required=True)
    resume_parser.add_argument("--actor", default="agent-b")

    args = parser.parse_args(argv)
    sophia = SophiaCli(args.db, oikonomia_db=args.oikonomia_db)
    try:
        if args.command == "run":
            path = args.analyst_json or args.generic_json
            payload = load_analyst_payload(path)
            extracted = extract_claims(payload)
            observations = _load_json(args.observations_json) if args.observations_json else None
            result = run_case(
                sophia,
                actor=args.actor,
                claims=extracted.claims,
                observations=observations if isinstance(observations, dict) else None,
            )
            result["transport_warnings"] = extracted.warnings
            json.dump(result, sys.stdout, indent=2, default=str)
            sys.stdout.write("\n")
            return 0
        resumed = resume_case(sophia, case_id=args.case_id)
        json.dump(resumed, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0
    except AnalystSurfaceError as exc:
        json.dump(
            {"error": {"code": exc.__class__.__name__, "message": str(exc)}},
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 2
    except SophiaProtocolError as exc:
        json.dump(exc.payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return exc.returncode


def _add_sophia_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, required=True, help="Sophia research ledger")
    parser.add_argument("--oikonomia-db", type=Path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
