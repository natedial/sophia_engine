"""AWS Cognito JWT validation for Sophia Canvas."""

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode

from sophia_canvas.config import get_settings

# Security scheme for OpenAPI docs
security = HTTPBearer(auto_error=False)


@dataclass
class CognitoUser:
    """Authenticated user from Cognito JWT."""

    user_id: str  # Cognito 'sub' claim
    email: str | None
    username: str | None
    groups: list[str]
    raw_claims: dict[str, Any]


class CognitoJWTValidator:
    """Validates JWTs from AWS Cognito User Pool."""

    def __init__(self, region: str, user_pool_id: str, client_id: str):
        self.region = region
        self.user_pool_id = user_pool_id
        self.client_id = client_id
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._jwks: dict[str, Any] | None = None
        self._jwks_last_fetch: float = 0
        self._jwks_ttl = 3600  # Cache JWKS for 1 hour

    async def _get_jwks(self) -> dict[str, Any]:
        """Fetch and cache JWKS from Cognito."""
        now = time.time()
        if self._jwks is None or (now - self._jwks_last_fetch) > self._jwks_ttl:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_url)
                response.raise_for_status()
                self._jwks = response.json()
                self._jwks_last_fetch = now
        return self._jwks

    async def _get_signing_key(self, token: str) -> dict[str, Any]:
        """Get the signing key for a token from JWKS."""
        # Decode header without verification to get kid
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        if not kid:
            raise JWTError("Token missing 'kid' header")

        jwks = await self._get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key

        raise JWTError(f"Unable to find signing key for kid: {kid}")

    async def validate_token(self, token: str) -> CognitoUser:
        """Validate a Cognito JWT and return the user."""
        try:
            # Get signing key
            signing_key = await self._get_signing_key(token)

            # Decode and validate token
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
                options={
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                },
            )

            # Extract user info
            return CognitoUser(
                user_id=claims["sub"],
                email=claims.get("email"),
                username=claims.get("cognito:username") or claims.get("username"),
                groups=claims.get("cognito:groups", []),
                raw_claims=claims,
            )

        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Unable to validate token: {str(e)}",
            )


@lru_cache
def get_validator() -> CognitoJWTValidator | None:
    """Get cached Cognito validator instance."""
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    if not settings.cognito_user_pool_id or not settings.cognito_client_id:
        return None
    return CognitoJWTValidator(
        region=settings.cognito_region,
        user_pool_id=settings.cognito_user_pool_id,
        client_id=settings.cognito_client_id,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> CognitoUser:
    """FastAPI dependency to get the authenticated user.

    Raises 401 if auth is enabled and token is missing/invalid.
    """
    settings = get_settings()

    # If auth is disabled, return a mock user for development
    if not settings.auth_enabled:
        return CognitoUser(
            user_id="dev-user",
            email="dev@example.com",
            username="developer",
            groups=[],
            raw_claims={},
        )

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    validator = get_validator()
    if not validator:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth configuration incomplete",
        )

    return await validator.validate_token(credentials.credentials)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> CognitoUser | None:
    """FastAPI dependency to optionally get the authenticated user.

    Returns None if auth is disabled or no token provided.
    Does not raise on missing token.
    """
    settings = get_settings()

    if not settings.auth_enabled:
        return CognitoUser(
            user_id="dev-user",
            email="dev@example.com",
            username="developer",
            groups=[],
            raw_claims={},
        )

    if not credentials:
        return None

    validator = get_validator()
    if not validator:
        return None

    try:
        return await validator.validate_token(credentials.credentials)
    except HTTPException:
        return None


async def validate_ws_token(token: str | None) -> CognitoUser | None:
    """Validate a token for WebSocket connections.

    WebSocket connections pass the token as a query parameter.
    """
    settings = get_settings()

    if not settings.auth_enabled:
        return CognitoUser(
            user_id="dev-user",
            email="dev@example.com",
            username="developer",
            groups=[],
            raw_claims={},
        )

    if not token:
        return None

    validator = get_validator()
    if not validator:
        return None

    try:
        return await validator.validate_token(token)
    except HTTPException:
        return None
