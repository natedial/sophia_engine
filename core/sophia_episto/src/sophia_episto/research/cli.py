"""JSON CLI for the source-neutral research protocol."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sophia_episto.research.engine import ResearchEngine
from sophia_episto.research.errors import ProtocolError
from sophia_episto.research.importer import import_legacy_graph


OPERATIONS = (
    "capabilities",
    "open_case",
    "get_case",
    "submit_evidence",
    "propose_hypothesis",
    "request_test",
    "get_run",
    "propose_assessment",
    "explain_case",
    "import_legacy_graph",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sophia-research",
        description="Sophia research-case protocol for outside agents",
    )
    parser.add_argument("--db", required=True, help="SQLite ledger path")
    parser.add_argument(
        "--oikonomia-db",
        help="Oikonomia SQLite path for test coordination (default: sibling of --db)",
    )
    parser.add_argument(
        "--payload",
        help="JSON payload file. Defaults to stdin for operations that need one.",
    )
    parser.add_argument("operation", choices=OPERATIONS)
    args = parser.parse_args(argv)

    payload = _read_payload(args.payload, args.operation)
    engine = ResearchEngine(
        Path(args.db),
        oikonomia_db=Path(args.oikonomia_db) if args.oikonomia_db else None,
    )
    try:
        if args.operation == "import_legacy_graph":
            result = import_legacy_graph(
                engine,
                payload.get("graph") or payload,
                actor=str(payload.get("actor") or "legacy-import"),
                question=payload.get("question"),
                case_id=payload.get("case_id"),
            )
        else:
            result = engine.dispatch(args.operation, payload)
    except ProtocolError as exc:
        json.dump(exc.to_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def _read_payload(path: str | None, operation: str) -> dict[str, Any]:
    if path is None and operation == "capabilities":
        return {}
    raw = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    if not raw.strip():
        return {}
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise SystemExit("Payload must be a JSON object")
    return loaded


if __name__ == "__main__":
    raise SystemExit(main())
