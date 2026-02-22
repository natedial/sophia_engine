"""Authentication module for Sophia Canvas."""

from sophia_canvas.auth.cognito import get_current_user, get_optional_user, CognitoUser

__all__ = ["get_current_user", "get_optional_user", "CognitoUser"]
