"""Authentication helpers for privileged Scrivener API operations."""

import secrets
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from src.config import get_settings

_api_key_header = APIKeyHeader(
    name="X-Scrivener-API-Key",
    auto_error=False,
    description="Service key required for ingestion and synchronization operations.",
)


def require_write_api_key(
    supplied_key: Annotated[str | None, Security(_api_key_header)],
) -> None:
    """Require the configured service key for operations that fetch or mutate data."""
    configured_key = get_settings().scrivener_api_key
    if not configured_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Privileged API operations are disabled until SCRIVENER_API_KEY is configured",
        )
    if supplied_key is None or not secrets.compare_digest(supplied_key, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Scrivener API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
