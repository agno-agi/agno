from os import getenv
from typing import List, Set

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agno.os.scopes import get_accessible_resource_ids
from agno.os.settings import AgnoAPISettings

# Create a global HTTPBearer instance
security = HTTPBearer(auto_error=False)


def _is_jwt_configured() -> bool:
    """Check if JWT authentication is configured via environment variables.

    This covers cases where JWT middleware is set up manually (not via authorization=True).
    """
    return bool(getenv("JWT_VERIFICATION_KEY") or getenv("JWT_JWKS_FILE"))


def get_authentication_dependency(settings: AgnoAPISettings):
    """
    Create an authentication dependency function for FastAPI routes.

    This handles security key authentication (OS_SECURITY_KEY).
    When JWT authorization is enabled (via authorization=True, JWT environment variables,
    or manually added JWT middleware), this dependency is skipped as JWT middleware
    handles authentication.

    Args:
        settings: The API settings containing the security key and authorization flag

    Returns:
        A dependency function that can be used with FastAPI's Depends()
    """

    async def auth_dependency(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> bool:
        # If JWT authorization is enabled via settings (authorization=True on AgentOS)
        if settings and settings.authorization_enabled:
            return True

        # Check if JWT middleware has already handled authentication
        if getattr(request.state, "authenticated", False):
            return True

        # Also skip if JWT is configured via environment variables
        if _is_jwt_configured():
            return True

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
    Validate a bearer token for WebSocket authentication (legacy os_security_key method).

    When JWT authorization is enabled (via authorization=True or JWT environment variables),
    this validation is skipped as JWT middleware handles authentication.

    Args:
        token: The bearer token to validate
        settings: The API settings containing the security key and authorization flag

    Returns:
        True if the token is valid or authentication is disabled, False otherwise
    """
    # If JWT authorization is enabled, skip security key validation
    if settings and settings.authorization_enabled:
        return True

    # Also skip if JWT is configured via environment variables (manual JWT middleware setup)
    if _is_jwt_configured():
        return True

    # If no security key is set, skip authentication entirely
    if not settings or not settings.os_security_key:
        return True

    # Verify the token matches the configured security key
    return token == settings.os_security_key


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

    # Get accessible resource IDs
    accessible_ids = get_accessible_resource_ids(user_scopes=user_scopes, resource_type=resource_type)

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


def require_resource_access(resource_type: str, action: str, resource_id_param: str):
    """
    Create a dependency that checks if the user has access to a specific resource.

    This dependency factory creates a FastAPI dependency that automatically checks
    authorization when authorization is enabled. It extracts the resource ID from
    the path parameters and verifies the user has the required access.

    Args:
        resource_type: Type of resource ("agents", "teams", "workflows")
        action: Action to check ("read", "run")
        resource_id_param: Name of the path parameter containing the resource ID

    Returns:
        A dependency function for use with FastAPI's Depends()

    Usage:
        @router.post("/agents/{agent_id}/runs")
        async def create_agent_run(
            agent_id: str,
            request: Request,
            _: None = Depends(require_resource_access("agents", "run", "agent_id")),
        ):
            ...

        @router.get("/agents/{agent_id}")
        async def get_agent(
            agent_id: str,
            request: Request,
            _: None = Depends(require_resource_access("agents", "read", "agent_id")),
        ):
            ...

    Examples:
        >>> # Creates dependency for checking agent run access
        >>> dep = require_resource_access("agents", "run", "agent_id")

        >>> # Creates dependency for checking team read access
        >>> dep = require_resource_access("teams", "read", "team_id")
    """
    # Map resource_type to singular form for error messages
    resource_singular = {
        "agents": "agent",
        "teams": "team",
        "workflows": "workflow",
    }.get(resource_type, resource_type.rstrip("s"))

    async def dependency(request: Request):
        # Only check authorization if it's enabled
        if not getattr(request.state, "authorization_enabled", False):
            return

        # Get the resource_id from path parameters
        resource_id = request.path_params.get(resource_id_param)
        if resource_id and not check_resource_access(request, resource_id, resource_type, action):
            raise HTTPException(status_code=403, detail=f"Access denied to {action} this {resource_singular}")

    return dependency
