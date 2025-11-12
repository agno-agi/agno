from typing import List

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agno.os.settings import AgnoAPISettings

# Create a global HTTPBearer instance
security = HTTPBearer(auto_error=False)


def get_authentication_dependency(settings: AgnoAPISettings):
    """
    Create an authentication dependency function for FastAPI routes.

    Args:
        settings: The API settings containing the security key

    Returns:
        A dependency function that can be used with FastAPI's Depends()
    """

    def auth_dependency(credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
        # If no security key is set, skip authentication entirely
        if not settings or not settings.os_security_key:
            return True

        # If security is enabled but no authorization header provided, fail
        if not credentials:
            raise HTTPException(status_code=401, detail="Authorization header required")

        token = credentials.credentials

        # Verify the token
        if token != settings.os_security_key:
            raise HTTPException(status_code=401, detail="Invalid authentication token")

        return True

    return auth_dependency


def validate_websocket_token(token: str, settings: AgnoAPISettings) -> bool:
    """
    Validate a bearer token for WebSocket authentication.

    Args:
        token: The bearer token to validate
        settings: The API settings containing the security key

    Returns:
        True if the token is valid or authentication is disabled, False otherwise
    """
    # If no security key is set, skip authentication entirely
    if not settings or not settings.os_security_key:
        return True

    # Verify the token matches the configured security key
    return token == settings.os_security_key


def require_scopes(required_scopes: List[str]):
    """
    Create a FastAPI dependency that checks for required scopes.

    This is a helper function for future use when you want to add
    scope requirements directly to specific endpoints using FastAPI's
    Depends() mechanism.

    Usage:
        @router.get("/endpoint", dependencies=[Depends(require_scopes(["scope:read"]))])
        async def my_endpoint():
            ...

    Args:
        required_scopes: List of scopes required to access the endpoint

    Returns:
        A dependency function that validates scopes
    """

    def scope_checker(request: Request) -> bool:
        # Check if user is authenticated
        if not getattr(request.state, "authenticated", False):
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
            )

        # Get user's scopes from request state (set by JWT middleware)
        user_scopes = getattr(request.state, "scopes", [])

        # Check for admin scope (grants all permissions)
        if "admin" in user_scopes:
            return True

        # Check if user has all required scopes
        for scope in required_scopes:
            if scope not in user_scopes:
                raise HTTPException(
                    status_code=403,
                    detail=f"Insufficient permissions. Required scopes: {required_scopes}",
                )

        return True

    return scope_checker
