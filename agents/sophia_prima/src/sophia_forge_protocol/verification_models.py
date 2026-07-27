"""Verification contracts for coding runtime runs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VerificationStep(BaseModel):
    """One verification command or recipe."""

    model_config = ConfigDict(extra="forbid")

    name: str
    command: str
    required: bool = True


class VerificationPolicy(BaseModel):
    """Requested verification mode for a coding run."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["none", "auto", "explicit"] = "auto"
    steps: tuple[VerificationStep, ...] = Field(default_factory=tuple)


class VerificationResult(BaseModel):
    """Outcome of one verification step or inferred check."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["passed", "failed", "skipped"]
    command: str = ""
    required: bool = True
    details: str = ""
