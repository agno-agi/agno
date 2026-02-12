"""AgentOS RBAC Scopes

This module defines all available permission scopes for AgentOS RBAC (Role-Based Access Control).

Scope Format:
- Global resource scopes: `resource:action`
- Per-resource scopes: `resource:<resource-id>:action`
- Wildcards: `resource:*:action` for any resource

The AgentOS ID is verified via the JWT `aud` (audience) claim.

Examples:
- `system:read` - Read system config
- `agents:read` - List all agents
- `agents:web-agent:read` - Read specific agent
- `agents:web-agent:run` - Run specific agent
- `agents:*:run` - Run any agent (wildcard)
- `agent_os:admin` - Full access to everything
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set


class AgentOSScope(str, Enum):
    """
    Enum of all available AgentOS permission scopes.

    Special Scopes:
    - ADMIN: Grants full access to all endpoints (agent_os:admin)

    Scope format:

    Global Resource Scopes:
    - system:read - System configuration and model information
    - agents:read - List all agents
    - teams:read - List all teams
    - workflows:read - List all workflows
    - sessions:read - View session data
    - sessions:write - Create and update sessions
    - sessions:delete - Delete sessions
    - memories:read - View memories
    - memories:write - Create and update memories
    - memories:delete - Delete memories
    - knowledge:read - View and search knowledge
    - knowledge:write - Add and update knowledge
    - knowledge:delete - Delete knowledge
    - metrics:read - View metrics
    - metrics:write - Refresh metrics
    - evals:read - View evaluation runs
    - evals:write - Create and update evaluation runs
    - evals:delete - Delete evaluation runs
    - traces:read - View traces and trace statistics

    Per-Resource Scopes (with resource ID):
    - agents:<agent-id>:read - Read specific agent
    - agents:<agent-id>:run - Run specific agent
    - teams:<team-id>:read - Read specific team
    - teams:<team-id>:run - Run specific team
    - workflows:<workflow-id>:read - Read specific workflow
    - workflows:<workflow-id>:run - Run specific workflow

    Wildcards:
    - agents:*:run - Run any agent
    - teams:*:run - Run any team
    """

    # Special scopes
    ADMIN = "agent_os:admin"


@dataclass
class ParsedScope:
    """Represents a parsed scope with its components."""

    raw: str
    scope_type: str  # "admin", "global", "per_resource", or "unknown"
    resource: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None
    is_wildcard_resource: bool = False

    @property
    def is_global_resource_scope(self) -> bool:
        """Check if this scope targets all resources of a type (no resource_id)."""
        return self.scope_type == "global"

    @property
    def is_per_resource_scope(self) -> bool:
        """Check if this scope targets a specific resource (has resource_id)."""
        return self.scope_type == "per_resource"


def parse_scope(scope: str, admin_scope: Optional[str] = None) -> ParsedScope:
    """
    Parse a scope string into its components.

    Args:
        scope: The scope string to parse
        admin_scope: The scope string that grants admin access (default: "agent_os:admin")

    Returns:
        ParsedScope object with parsed components

    Examples:
        >>> parse_scope("agent_os:admin")
        ParsedScope(raw="agent_os:admin", scope_type="admin")

        >>> parse_scope("system:read")
        ParsedScope(raw="system:read", scope_type="global", resource="system", action="read")

        >>> parse_scope("agents:web-agent:read")
        ParsedScope(raw="...", scope_type="per_resource", resource="agents", resource_id="web-agent", action="read")

        >>> parse_scope("agents:*:run")
        ParsedScope(raw="...", scope_type="per_resource", resource="agents", resource_id="*", action="run", is_wildcard_resource=True)
    """
    effective_admin_scope = admin_scope or AgentOSScope.ADMIN.value
    if scope == effective_admin_scope:
        return ParsedScope(raw=scope, scope_type="admin")

    parts = scope.split(":")

    # Global resource scope: resource:action (2 parts)
    if len(parts) == 2:
        return ParsedScope(
            raw=scope,
            scope_type="global",
            resource=parts[0],
            action=parts[1],
        )

    # Per-resource scope: resource:<resource-id>:action (3 parts)
    if len(parts) == 3:
        resource_id = parts[1]
        is_wildcard_resource = resource_id == "*"

        return ParsedScope(
            raw=scope,
            scope_type="per_resource",
            resource=parts[0],
            resource_id=resource_id,
            action=parts[2],
            is_wildcard_resource=is_wildcard_resource,
        )

    # Invalid format
    return ParsedScope(raw=scope, scope_type="unknown")


def matches_scope(
    user_scope: ParsedScope,
    required_scope: ParsedScope,
    resource_id: Optional[str] = None,
) -> bool:
    """
    Check if a user's scope matches a required scope.

    Args:
        user_scope: The user's parsed scope
        required_scope: The required parsed scope
        resource_id: The specific resource ID being accessed

    Returns:
        True if the user's scope satisfies the required scope

    Examples:
        >>> user = parse_scope("system:read")
        >>> required = parse_scope("system:read")
        >>> matches_scope(user, required)
        True

        >>> user = parse_scope("agents:web-agent:run")
        >>> required = parse_scope("agents:<id>:run")
        >>> matches_scope(user, required, resource_id="web-agent")
        True

        >>> user = parse_scope("agents:*:run")
        >>> required = parse_scope("agents:<id>:run")
        >>> matches_scope(user, required, resource_id="web-agent")
        True
    """
    # Admin always matches
    if user_scope.scope_type == "admin":
        return True

    # Unknown scopes don't match anything
    if user_scope.scope_type == "unknown" or required_scope.scope_type == "unknown":
        return False

    # Resource type must match
    if user_scope.resource != required_scope.resource:
        return False

    # Action must match
    if user_scope.action != required_scope.action:
        return False

    # If required scope has a resource_id, check it
    if required_scope.resource_id:
        # User has wildcard resource access
        if user_scope.is_wildcard_resource:
            return True
        # User has global resource access (no resource_id in user scope)
        if not user_scope.resource_id:
            return True
        # User has specific resource access - must match
        return user_scope.resource_id == resource_id

    # Required scope is global (no resource_id), user scope matches if:
    # - User has global scope (no resource_id), OR
    # - User has wildcard resource scope
    return not user_scope.resource_id or user_scope.is_wildcard_resource


def has_required_scopes(
    user_scopes: List[str],
    required_scopes: List[str],
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    admin_scope: Optional[str] = None,
) -> bool:
    """
    Check if user has all required scopes.

    Args:
        user_scopes: List of scope strings the user has
        required_scopes: List of scope strings required
        resource_type: Type of resource being accessed ("agents", "teams", "workflows")
        resource_id: Specific resource ID being accessed
        admin_scope: The scope string that grants admin access (default: "agent_os:admin")

    Returns:
        True if user has all required scopes

    Examples:
        >>> has_required_scopes(
        ...     ["agents:read"],
        ...     ["agents:read"],
        ... )
        True

        >>> has_required_scopes(
        ...     ["agents:web-agent:run"],
        ...     ["agents:run"],
        ...     resource_type="agents",
        ...     resource_id="web-agent"
        ... )
        True

        >>> has_required_scopes(
        ...     ["agents:*:run"],
        ...     ["agents:run"],
        ...     resource_type="agents",
        ...     resource_id="any-agent"
        ... )
        True
    """
    if not required_scopes:
        return True

    # Parse user scopes once
    parsed_user_scopes = [parse_scope(scope, admin_scope=admin_scope) for scope in user_scopes]

    # Check for admin scope
    if any(s.scope_type == "admin" for s in parsed_user_scopes):
        return True

    # Check each required scope
    for required_scope_str in required_scopes:
        parts = required_scope_str.split(":")
        if len(parts) == 2:
            resource, action = parts
            # Build the required scope based on context
            if resource_id and resource_type:
                # Per-resource scope required
                full_required_scope = f"{resource_type}:<resource-id>:{action}"
            else:
                # Global resource scope required
                full_required_scope = required_scope_str

            required = parse_scope(full_required_scope, admin_scope=admin_scope)
        else:
            required = parse_scope(required_scope_str, admin_scope=admin_scope)

        scope_matched = False
        for user_scope in parsed_user_scopes:
            if matches_scope(user_scope, required, resource_id=resource_id):
                scope_matched = True
                break

        if not scope_matched:
            return False

    return True


def get_accessible_resource_ids(
    user_scopes: List[str],
    resource_type: str,
    admin_scope: Optional[str] = None,
) -> Set[str]:
    """
    Get the set of resource IDs the user has access to.

    Args:
        user_scopes: List of scope strings the user has
        resource_type: Type of resource ("agents", "teams", "workflows")
        admin_scope: The scope string that grants admin access (default: "agent_os:admin")

    Returns:
        Set of resource IDs the user can access. Returns {"*"} for wildcard access.

    Examples:
        >>> get_accessible_resource_ids(
        ...     ["agents:agent-1:read", "agents:agent-2:read"],
        ...     "agents"
        ... )
        {'agent-1', 'agent-2'}

        >>> get_accessible_resource_ids(["agents:*:read"], "agents")
        {'*'}

        >>> get_accessible_resource_ids(["agents:read"], "agents")
        {'*'}

        >>> get_accessible_resource_ids(["admin"], "agents")
        {'*'}
    """
    parsed_scopes = [parse_scope(scope, admin_scope=admin_scope) for scope in user_scopes]

    # Check for admin or global wildcard access
    for scope in parsed_scopes:
        if scope.scope_type == "admin":
            return {"*"}

        # Check if resource type matches
        if scope.resource == resource_type:
            # Global resource scope (no resource_id) grants access to all
            if not scope.resource_id and scope.action in ["read", "run"]:
                return {"*"}
            # Wildcard resource scope grants access to all
            if scope.is_wildcard_resource and scope.action in ["read", "run"]:
                return {"*"}

    # Collect specific resource IDs
    accessible_ids: Set[str] = set()
    for scope in parsed_scopes:
        # Check if resource type matches
        if scope.resource == resource_type:
            # Specific resource ID
            if scope.resource_id and not scope.is_wildcard_resource and scope.action in ["read", "run"]:
                accessible_ids.add(scope.resource_id)

    return accessible_ids


def get_default_scope_mappings() -> Dict[str, List[str]]:
    """
    Get default scope mappings for AgentOS endpoints.

    Returns a dictionary mapping route patterns (with HTTP methods) to required scope templates.
    Format: "METHOD /path/pattern": ["resource:action"]
    """
    return {
        # System endpoints
        "GET /config": ["system:read"],
        "GET /models": ["system:read"],
        # Agent endpoints
        "GET /agents": ["agents:read"],
        "GET /agents/*": ["agents:read"],
        "POST /agents": ["agents:write"],
        "PATCH /agents/*": ["agents:write"],
        "DELETE /agents/*": ["agents:delete"],
        "POST /agents/*/runs": ["agents:run"],
        "POST /agents/*/runs/*/continue": ["agents:run"],
        "POST /agents/*/runs/*/cancel": ["agents:run"],
        # Team endpoints
        "GET /teams": ["teams:read"],
        "GET /teams/*": ["teams:read"],
        "POST /teams": ["teams:write"],
        "PATCH /teams/*": ["teams:write"],
        "DELETE /teams/*": ["teams:delete"],
        "POST /teams/*/runs": ["teams:run"],
        "POST /teams/*/runs/*/continue": ["teams:run"],
        "POST /teams/*/runs/*/cancel": ["teams:run"],
        # Workflow endpoints
        "GET /workflows": ["workflows:read"],
        "GET /workflows/*": ["workflows:read"],
        "POST /workflows": ["workflows:write"],
        "PATCH /workflows/*": ["workflows:write"],
        "DELETE /workflows/*": ["workflows:delete"],
        "POST /workflows/*/runs": ["workflows:run"],
        "POST /workflows/*/runs/*/continue": ["workflows:run"],
        "POST /workflows/*/runs/*/cancel": ["workflows:run"],
        # Session endpoints
        "GET /sessions": ["sessions:read"],
        "GET /sessions/*": ["sessions:read"],
        "POST /sessions": ["sessions:write"],
        "POST /sessions/*/rename": ["sessions:write"],
        "PATCH /sessions/*": ["sessions:write"],
        "DELETE /sessions": ["sessions:delete"],
        "DELETE /sessions/*": ["sessions:delete"],
        # Memory endpoints
        "GET /memories": ["memories:read"],
        "GET /memories/*": ["memories:read"],
        "GET /memory_topics": ["memories:read"],
        "GET /user_memory_stats": ["memories:read"],
        "POST /memories": ["memories:write"],
        "PATCH /memories/*": ["memories:write"],
        "DELETE /memories": ["memories:delete"],
        "DELETE /memories/*": ["memories:delete"],
        "POST /optimize-memories": ["memories:write"],
        # Knowledge endpoints
        "GET /knowledge/content": ["knowledge:read"],
        "GET /knowledge/content/*": ["knowledge:read"],
        "GET /knowledge/config": ["knowledge:read"],
        "POST /knowledge/content": ["knowledge:write"],
        "PATCH /knowledge/content/*": ["knowledge:write"],
        "POST /knowledge/search": ["knowledge:read"],
        "DELETE /knowledge/content": ["knowledge:delete"],
        "DELETE /knowledge/content/*": ["knowledge:delete"],
        # Metrics endpoints
        "GET /metrics": ["metrics:read"],
        "POST /metrics/refresh": ["metrics:write"],
        # Evaluation endpoints
        "GET /eval-runs": ["evals:read"],
        "GET /eval-runs/*": ["evals:read"],
        "POST /eval-runs": ["evals:write"],
        "PATCH /eval-runs/*": ["evals:write"],
        "DELETE /eval-runs": ["evals:delete"],
        # Trace endpoints
        "GET /traces": ["traces:read"],
        "GET /traces/*": ["traces:read"],
        "GET /trace_session_stats": ["traces:read"],
        # Schedule endpoints
        "GET /schedules": ["schedules:read"],
        "GET /schedules/*": ["schedules:read"],
        "POST /schedules": ["schedules:write"],
        "PATCH /schedules/*": ["schedules:write"],
        "DELETE /schedules/*": ["schedules:delete"],
        "POST /schedules/*/enable": ["schedules:write"],
        "POST /schedules/*/disable": ["schedules:write"],
        "POST /schedules/*/trigger": ["schedules:write"],
        "GET /schedules/*/runs": ["schedules:read"],
        "GET /schedules/*/runs/*": ["schedules:read"],
        # Approval endpoints
        "GET /approvals": ["approvals:read"],
        "GET /approvals/count": ["approvals:read"],
        "GET /approvals/*": ["approvals:read"],
        "POST /approvals/*/resolve": ["approvals:write"],
        "DELETE /approvals/*": ["approvals:delete"],
    }


def get_scope_value(scope: AgentOSScope) -> str:
    """
    Get the string value of a scope.

    Args:
        scope: The AgentOSScope enum value

    Returns:
        The string value of the scope

    Example:
        >>> get_scope_value(AgentOSScope.ADMIN)
        'admin'
    """
    return scope.value


def get_all_scopes() -> list[str]:
    """
    Get a list of all available scope strings.

    Returns:
        List of all scope string values

    Example:
        >>> scopes = get_all_scopes()
        >>> 'admin' in scopes
        True
    """
    return [scope.value for scope in AgentOSScope]
