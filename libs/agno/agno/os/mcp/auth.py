"""Authentication utilities for MCP tools."""

from typing import Optional

from fastmcp import Context

from agno.os.settings import AgnoAPISettings


def validate_mcp_auth(ctx: Context, settings: Optional[AgnoAPISettings] = None) -> bool:
    """
    Validate authentication for MCP tool calls using Bearer token.

    This mirrors the authentication logic used in REST endpoints via
    `get_authentication_dependency` in agno.os.auth.

    Args:
        ctx: The FastMCP Context object
        settings: The API settings containing the security key

    Returns:
        True if authentication passes

    Raises:
        Exception: If authentication fails
    """
    # If no security key is set, skip authentication entirely
    if not settings or not settings.os_security_key:
        return True

    # Try to get the request from the MCP context
    request_context = ctx.request_context
    if not request_context:
        raise Exception("Authorization required but no request context available")

    request = request_context.request
    if not request:
        raise Exception("Authorization required but no HTTP request available")

    # Get the Authorization header
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header:
        raise Exception("Authorization header required")

    # Parse Bearer token
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise Exception("Invalid authorization header format. Expected: Bearer <token>")

    token = parts[1]

    # Verify the token
    if token != settings.os_security_key:
        raise Exception("Invalid authentication token")

    return True


def get_user_id_from_context(ctx: Context) -> Optional[str]:
    """
    Extract user_id from the MCP context if available.

    In authenticated scenarios, the user_id might be set on the request state
    by authentication middleware.

    Args:
        ctx: The FastMCP Context object

    Returns:
        The user_id if available, None otherwise
    """
    request_context = ctx.request_context
    if not request_context or not request_context.request:
        return None

    request = request_context.request
    # Check if user_id is set on request state (similar to REST endpoints)
    if hasattr(request, "state") and hasattr(request.state, "user_id"):
        return request.state.user_id

    return None

