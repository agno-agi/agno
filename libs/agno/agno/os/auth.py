from typing import Optional

from fastapi import Header, HTTPException

from agno.os.settings import AgnoAPISettings


def verify_bearer_token(
    authorization: Optional[str] = Header(None),
    settings: Optional["AgnoAPISettings"] = None,
) -> bool:
    """
    Verify the bearer token from the Authorization header.

    Args:
        authorization: The Authorization header value
        settings: The API settings containing the security key

    Returns:
        bool: True if authentication is successful or disabled

    Raises:
        HTTPException: If authentication fails
    """
    # If no security key is set, skip authentication
    if not settings or not settings.os_security_key:
        return True

    # If no authorization header is provided, authentication fails
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    # Check if the authorization header starts with "Bearer "
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format. Expected 'Bearer <token>'")

    # Extract the token from the authorization header
    token = authorization[7:]  # Remove "Bearer " prefix

    # Compare the token with the expected security key
    if token != settings.os_security_key:
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    return True


def get_authentication_dependency(settings: "AgnoAPISettings"):
    """
    Create an authentication dependency function for FastAPI routes.

    Args:
        settings: The API settings containing the security key

    Returns:
        A dependency function that can be used with FastAPI's Depends()
    """

    def auth_dependency(authorization: Optional[str] = Header(None)) -> bool:
        return verify_bearer_token(authorization, settings)

    return auth_dependency
