"""Sophia public-interface client.

Invokes the `sophia-research` JSON CLI as a subprocess. The outside agent
does not import Episto internals or open Sophia's SQLite files directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


class SophiaProtocolError(RuntimeError):
    def __init__(self, payload: dict[str, Any], *, returncode: int) -> None:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        message = str(error.get("message") or payload or "Sophia protocol error")
        super().__init__(message)
        self.payload = payload
        self.returncode = returncode
        self.code = error.get("code")
        self.details = error.get("details") or {}


class SophiaCli:
    def __init__(
        self,
        db_path: Path,
        *,
        python: str | None = None,
        oikonomia_db: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.python = python or sys.executable
        self.oikonomia_db = Path(oikonomia_db) if oikonomia_db else None
        self.env = env

    def invoke(self, operation: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        command = [
            self.python,
            "-m",
            "sophia_episto.research",
            "--db",
            str(self.db_path),
        ]
        if self.oikonomia_db is not None:
            command.extend(["--oikonomia-db", str(self.oikonomia_db)])
        payload_file = None
        try:
            if payload:
                handle = tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".json",
                    delete=False,
                    encoding="utf-8",
                )
                payload_file = Path(handle.name)
                with handle:
                    json.dump(payload, handle)
                    handle.write("\n")
                command.extend(["--payload", str(payload_file)])
            command.append(operation)
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=self.env or os.environ.copy(),
            )
        finally:
            if payload_file is not None:
                payload_file.unlink(missing_ok=True)

        parsed = _parse_json(completed.stdout)
        if completed.returncode != 0:
            if isinstance(parsed, dict) and parsed.get("error"):
                raise SophiaProtocolError(parsed, returncode=completed.returncode)
            raise RuntimeError(
                f"sophia-research {operation} failed ({completed.returncode}): "
                f"{completed.stderr or completed.stdout}"
            )
        if not isinstance(parsed, dict):
            raise RuntimeError(f"sophia-research {operation} returned non-object JSON")
        return parsed


def _parse_json(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return {}
    return json.loads(text)
