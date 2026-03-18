"""Shared helpers for classifying forge run outcomes."""

from __future__ import annotations

from sophia_forge_protocol.verification_models import VerificationResult


def classify_failure(*, status: str, error: str | None) -> str:
    """Normalize runtime failures into a small set of operational classes."""

    detail = (error or "").lower()
    if status == "timed_out":
        return "timed_out"
    if status == "blocked":
        return "blocked"
    if status == "permission_denied":
        return "permission_denied"
    if status == "invalid_output":
        return "invalid_output"
    if status == "unavailable":
        return "backend_unavailable"
    if status == "disabled":
        return "disabled"
    if status == "cancelled":
        return "cancelled"
    if "verification" in detail and "failed" in detail:
        return "verification_failed"
    if "launch failed" in detail:
        return "backend_launch_failed"
    if detail:
        return "execution_failed"
    return "failed"


def required_verification_passed(
    results: tuple[VerificationResult, ...],
) -> bool | None:
    """Return whether all required verification steps passed, or None when absent."""

    if not results:
        return None
    required_results = [result for result in results if result.required]
    if not required_results:
        return True
    return all(result.status == "passed" for result in required_results)
