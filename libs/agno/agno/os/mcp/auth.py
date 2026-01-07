"""Authentication utilities for MCP tools."""

from typing import TYPE_CHECKING, List, Optional, Set, Union

from fastmcp import Context

if TYPE_CHECKING:
    from agno.agent.agent import Agent
    from agno.agent.remote import RemoteAgent
    from agno.team import RemoteTeam, Team
    from agno.workflow.remote import RemoteWorkflow
    from agno.workflow.workflow import Workflow


def get_request_from_context(ctx: Context):
    """Get the Starlette request from MCP context.

    Args:
        ctx: The FastMCP Context object

    Returns:
        The Starlette Request object or None
    """
    request_context = ctx.request_context
    if not request_context:
        return None
    return request_context.request


def is_authorization_enabled(ctx: Context) -> bool:
    """Check if authorization is enabled for the current request.

    Args:
        ctx: The FastMCP Context object

    Returns:
        True if authorization is enabled
    """
    request = get_request_from_context(ctx)
    if not request:
        return False
    return getattr(request.state, "authorization_enabled", False)


def get_user_id_from_context(ctx: Context) -> Optional[str]:
    """Extract user_id from the MCP context if available.

    Args:
        ctx: The FastMCP Context object

    Returns:
        The user_id if available, None otherwise
    """
    request = get_request_from_context(ctx)
    if not request:
        return None
    return getattr(request.state, "user_id", None)


def get_scopes_from_context(ctx: Context) -> List[str]:
    """Extract scopes from the MCP context if available.

    Args:
        ctx: The FastMCP Context object

    Returns:
        List of scopes, empty list if not available
    """
    request = get_request_from_context(ctx)
    if not request:
        return []
    return getattr(request.state, "scopes", [])


def get_accessible_resource_ids(ctx: Context, resource_type: str) -> Set[str]:
    """Get the set of resource IDs the user has access to based on their scopes.

    This mirrors the logic in agno.os.auth.get_accessible_resources().

    Args:
        ctx: The FastMCP Context object
        resource_type: Type of resource ("agents", "teams", "workflows")

    Returns:
        Set of resource IDs the user can access. Returns {"*"} for wildcard access.
    """
    request = get_request_from_context(ctx)
    if not request:
        return {"*"}  # No request context = allow all

    # Check if accessible_resource_ids is already cached in request state
    cached_ids = getattr(request.state, "accessible_resource_ids", None)
    if cached_ids is not None:
        return cached_ids

    # Get user's scopes from request state
    user_scopes = getattr(request.state, "scopes", [])

    # Import and use the scopes utility
    from agno.os.scopes import get_accessible_resource_ids as _get_accessible_resource_ids

    return _get_accessible_resource_ids(user_scopes=user_scopes, resource_type=resource_type)


def filter_agents_by_access(
    ctx: Context, agents: List[Union["Agent", "RemoteAgent"]]
) -> List[Union["Agent", "RemoteAgent"]]:
    """Filter a list of agents based on user's access permissions.

    Args:
        ctx: The FastMCP Context object
        agents: List of Agent or RemoteAgent objects

    Returns:
        Filtered list of agents the user has access to
    """
    if not is_authorization_enabled(ctx):
        return agents

    accessible_ids = get_accessible_resource_ids(ctx, "agents")

    # Wildcard access - return all
    if "*" in accessible_ids:
        return agents

    # Filter to only accessible
    return [a for a in agents if a.id in accessible_ids]


def filter_teams_by_access(ctx: Context, teams: List[Union["Team", "RemoteTeam"]]) -> List[Union["Team", "RemoteTeam"]]:
    """Filter a list of teams based on user's access permissions.

    Args:
        ctx: The FastMCP Context object
        teams: List of Team objects

    Returns:
        Filtered list of teams the user has access to
    """
    if not is_authorization_enabled(ctx):
        return teams

    accessible_ids = get_accessible_resource_ids(ctx, "teams")

    # Wildcard access - return all
    if "*" in accessible_ids:
        return teams

    # Filter to only accessible
    return [t for t in teams if t.id in accessible_ids]


def filter_workflows_by_access(
    ctx: Context, workflows: List[Union["Workflow", "RemoteWorkflow"]]
) -> List[Union["Workflow", "RemoteWorkflow"]]:
    """Filter a list of workflows based on user's access permissions.

    Args:
        ctx: The FastMCP Context object
        workflows: List of Workflow objects

    Returns:
        Filtered list of workflows the user has access to
    """
    if not is_authorization_enabled(ctx):
        return workflows

    accessible_ids = get_accessible_resource_ids(ctx, "workflows")

    # Wildcard access - return all
    if "*" in accessible_ids:
        return workflows

    # Filter to only accessible
    return [w for w in workflows if w.id in accessible_ids]


def check_resource_access(ctx: Context, resource_id: str, resource_type: str) -> bool:
    """Check if user has access to a specific resource.

    Args:
        ctx: The FastMCP Context object
        resource_id: ID of the resource to check
        resource_type: Type of resource ("agents", "teams", "workflows")

    Returns:
        True if user has access, False otherwise
    """
    if not is_authorization_enabled(ctx):
        return True

    accessible_ids = get_accessible_resource_ids(ctx, resource_type)

    # Wildcard access grants all permissions
    if "*" in accessible_ids:
        return True

    return resource_id in accessible_ids


def require_resource_access(ctx: Context, resource_id: str, resource_type: str) -> None:
    """Require access to a specific resource, raise exception if denied.

    Args:
        ctx: The FastMCP Context object
        resource_id: ID of the resource to check
        resource_type: Type of resource ("agents", "teams", "workflows")

    Raises:
        Exception: If access is denied
    """
    if not check_resource_access(ctx, resource_id, resource_type):
        resource_singular = resource_type.rstrip("s")
        raise Exception(f"Access denied to this {resource_singular}")
