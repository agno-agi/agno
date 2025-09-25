from fastapi import Depends, HTTPException
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
