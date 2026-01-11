#!/usr/bin/env python3
"""Validate symbology.json against metadata.json for root symbol ambiguity."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def load_allowed_roots(metadata_path: Path) -> set[str]:
    """Load allowed root symbols from Databento metadata.json."""
    data = json.loads(metadata_path.read_text())
    symbols = data.get("query", {}).get("symbols", [])
    roots = {symbol.split(".")[0] for symbol in symbols}
    if not roots:
        raise ValueError("No symbols found in metadata.json")
    return roots


def infer_root(symbology_key: str, allowed_roots: set[str]) -> set[str]:
    """Return all matching roots in a symbology key."""
    tokens = re.findall(r"[A-Z0-9]+", symbology_key)
    roots = {root for token in tokens for root in allowed_roots if token.startswith(root)}
    return roots


def validate_symbology(symbology_path: Path, allowed_roots: set[str]) -> list[str]:
    """Return list of symbology keys that are ambiguous or missing a root."""
    data = json.loads(symbology_path.read_text())
    result = data.get("result", {})
    errors = []
    for key in result.keys():
        roots = infer_root(key, allowed_roots)
        if len(roots) != 1:
            errors.append(key)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate symbology.json root mappings against metadata.json"
    )
    parser.add_argument("--metadata", type=Path, required=True, help="Path to metadata.json")
    parser.add_argument("--symbology", type=Path, required=True, help="Path to symbology.json")
    args = parser.parse_args()

    try:
        allowed_roots = load_allowed_roots(args.metadata)
    except Exception as exc:
        print(f"Failed to load metadata: {exc}", file=sys.stderr)
        return 2

    errors = validate_symbology(args.symbology, allowed_roots)
    if errors:
        print(f"Ambiguous or missing root in {len(errors)} symbology keys:", file=sys.stderr)
        for key in errors[:50]:
            print(f"- {key}", file=sys.stderr)
        if len(errors) > 50:
            print(f"... and {len(errors) - 50} more", file=sys.stderr)
        return 1

    print("All symbology keys map to exactly one allowed root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
