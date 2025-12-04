from typing import List, Set

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agno.os.scopes import get_accessible_resource_ids
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


def get_accessible_resources(request: Request, resource_type: str) -> Set[str]:
    """
    Get the set of resource IDs the user has access to based on their scopes.

    This function is used to filter lists of resources (agents, teams, workflows)
    based on the user's scopes from their JWT token.

    Args:
        request: The FastAPI request object (contains request.state.scopes)
        resource_type: Type of resource ("agents", "teams", "workflows")

    Returns:
        Set of resource IDs the user can access. Returns {"*"} for wildcard access.

    Usage:
        accessible_ids = get_accessible_resources(request, "agents")
        if "*" not in accessible_ids:
            agents = [a for a in agents if a.id in accessible_ids]

    Examples:
        >>> # User with specific agent access
        >>> # Token scopes: ["agent-os:my-os:agents:my-agent:read"]
        >>> get_accessible_resources(request, "agents")
        {'my-agent'}

        >>> # User with wildcard access
        >>> # Token scopes: ["agent-os:my-os:agents:*:read"] or ["admin"]
        >>> get_accessible_resources(request, "agents")
        {'*'}

        >>> # User with agent-os level access (global resource scope)
        >>> # Token scopes: ["agent-os:my-os:agents:read"]
        >>> get_accessible_resources(request, "agents")
        {'*'}
    """
    # Check if accessible_resource_ids is already cached in request state (set by JWT middleware)
    # This happens when user doesn't have global scope but has specific resource scopes
    cached_ids = getattr(request.state, "accessible_resource_ids", None)
    if cached_ids is not None:
        return cached_ids

    # Get user's scopes from request state (set by JWT middleware)
    user_scopes = getattr(request.state, "scopes", [])

    # Get agent_os_id from app state
    agent_os_id = getattr(request.app.state, "agent_os_id", None)

    # Get accessible resource IDs
    accessible_ids = get_accessible_resource_ids(
        user_scopes=user_scopes, resource_type=resource_type
    )

    return accessible_ids


def filter_resources_by_access(request: Request, resources: List, resource_type: str) -> List:
    """
    Filter a list of resources based on user's access permissions.

    Args:
        request: The FastAPI request object
        resources: List of resource objects (agents, teams, or workflows) with 'id' attribute
        resource_type: Type of resource ("agents", "teams", "workflows")

    Returns:
        Filtered list of resources the user has access to

    Usage:
        agents = filter_resources_by_access(request, all_agents, "agents")
        teams = filter_resources_by_access(request, all_teams, "teams")
        workflows = filter_resources_by_access(request, all_workflows, "workflows")

    Examples:
        >>> # User with specific access
        >>> agents = [Agent(id="agent-1"), Agent(id="agent-2"), Agent(id="agent-3")]
        >>> # Token scopes: ["agent-os:my-os:agents:agent-1:read", "agent-os:my-os:agents:agent-2:read"]
        >>> filter_resources_by_access(request, agents, "agents")
        [Agent(id="agent-1"), Agent(id="agent-2")]

        >>> # User with wildcard access
        >>> # Token scopes: ["admin"]
        >>> filter_resources_by_access(request, agents, "agents")
        [Agent(id="agent-1"), Agent(id="agent-2"), Agent(id="agent-3")]
    """
    accessible_ids = get_accessible_resources(request, resource_type)

    # Wildcard access - return all resources
    if "*" in accessible_ids:
        return resources

    # Filter to only accessible resources
    return [r for r in resources if r.id in accessible_ids]


def check_resource_access(request: Request, resource_id: str, resource_type: str, action: str = "read") -> bool:
    """
    Check if user has access to a specific resource.

    Args:
        request: The FastAPI request object
        resource_id: ID of the resource to check
        resource_type: Type of resource ("agents", "teams", "workflows")
        action: Action to check ("read", "run", etc.)

    Returns:
        True if user has access, False otherwise

    Usage:
        if not check_resource_access(request, agent_id, "agents", "run"):
            raise HTTPException(status_code=403, detail="Access denied")

    Examples:
        >>> # Token scopes: ["agent-os:my-os:agents:my-agent:read", "agent-os:my-os:agents:my-agent:run"]
        >>> check_resource_access(request, "my-agent", "agents", "run")
        True

        >>> check_resource_access(request, "other-agent", "agents", "run")
        False
    """
    accessible_ids = get_accessible_resources(request, resource_type)

    # Wildcard access grants all permissions
    if "*" in accessible_ids:
        return True

    # Check if user has access to this specific resource
    return resource_id in accessible_ids
