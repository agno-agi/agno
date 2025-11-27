"""AgentOS RBAC Scopes

This module defines all available permission scopes for AgentOS RBAC (Role-Based Access Control).

Scope Format:
ALL scopes use the agent-os namespace:
- Global resource scopes: `agent-os:<os-id>:resource:action`
- Per-resource scopes: `agent-os:<os-id>:resource:<resource-id>:action`
- Wildcards supported at any level: `agent-os:*:...` or `agent-os:<os-id>:agents:*:run`

Examples:
- `agent-os:my-os:system:read` - Read system config for specific AgentOS instance
- `agent-os:my-os:agents:read` - List all agents in my-os
- `agent-os:my-os:agents:web-agent:read` - Read specific agent in my-os
- `agent-os:my-os:agents:web-agent:run` - Run specific agent in my-os
- `agent-os:*:agents:read` - List agents from any AgentOS instance
- `agent-os:my-os:agents:*:run` - Run any agent in my-os
- `agent-os:*:agents:*:run` - Run any agent in any AgentOS instance
- `admin` - Full access to everything
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set
import fnmatch


class AgentOSScope(str, Enum):
    """
    Enum of all available AgentOS permission scopes.

    Special Scopes:
    - ADMIN: Grants full access to all endpoints

    ALL scopes use agent-os namespace format:
    
    Global Resource Scopes:
    - agent-os:<id>:system:read - System configuration and model information
    - agent-os:<id>:agents:read - List all agents
    - agent-os:<id>:teams:read - List all teams
    - agent-os:<id>:workflows:read - List all workflows
    - agent-os:<id>:sessions:read - View session data
    - agent-os:<id>:sessions:write - Create and update sessions
    - agent-os:<id>:sessions:delete - Delete sessions
    - agent-os:<id>:memories:read - View memories
    - agent-os:<id>:memories:write - Create and update memories
    - agent-os:<id>:memories:delete - Delete memories
    - agent-os:<id>:knowledge:read - View and search knowledge
    - agent-os:<id>:knowledge:write - Add and update knowledge
    - agent-os:<id>:knowledge:delete - Delete knowledge
    - agent-os:<id>:metrics:read - View metrics
    - agent-os:<id>:metrics:write - Refresh metrics
    - agent-os:<id>:evals:read - View evaluation runs
    - agent-os:<id>:evals:write - Create and update evaluation runs
    - agent-os:<id>:evals:delete - Delete evaluation runs

    Per-Resource Scopes (with resource ID):
    - agent-os:<id>:agents:<agent-id>:read - Read specific agent
    - agent-os:<id>:agents:<agent-id>:run - Run specific agent
    - agent-os:<id>:teams:<team-id>:read - Read specific team
    - agent-os:<id>:teams:<team-id>:run - Run specific team
    - agent-os:<id>:workflows:<workflow-id>:read - Read specific workflow
    - agent-os:<id>:workflows:<workflow-id>:run - Run specific workflow
    
    Wildcards:
    - agent-os:*:agents:read - List agents from any OS
    - agent-os:<id>:agents:*:run - Run any agent in this OS
    - agent-os:*:agents:*:run - Run any agent in any OS
    """

    # Special scopes
    ADMIN = "admin"


@dataclass
class ParsedScope:
    """Represents a parsed scope with its components."""

    raw: str
    scope_type: str  # "admin" or "agent-os"
    agent_os_id: Optional[str] = None
    resource: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None
    is_wildcard_os: bool = False
    is_wildcard_resource: bool = False

    @property
    def is_agent_os_scope(self) -> bool:
        """Check if this is an agent-os scoped permission."""
        return self.scope_type == "agent-os"

    @property
    def is_per_resource_scope(self) -> bool:
        """Check if this scope targets a specific resource (has resource_id)."""
        return self.resource_id is not None

    @property
    def is_global_resource_scope(self) -> bool:
        """Check if this scope targets all resources of a type (no resource_id)."""
        return self.resource is not None and self.resource_id is None


def parse_scope(scope: str) -> ParsedScope:
    """
    Parse a scope string into its components.

    Args:
        scope: The scope string to parse

    Returns:
        ParsedScope object with parsed components

    Examples:
        >>> parse_scope("admin")
        ParsedScope(raw="admin", scope_type="admin")

        >>> parse_scope("agent-os:my-os:system:read")
        ParsedScope(raw="...", scope_type="agent-os", agent_os_id="my-os", resource="system", action="read")

        >>> parse_scope("agent-os:*:agents:read")
        ParsedScope(raw="...", scope_type="agent-os", agent_os_id="*", resource="agents", action="read", is_wildcard_os=True)

        >>> parse_scope("agent-os:my-os:agents:web-agent:read")
        ParsedScope(raw="...", scope_type="agent-os", agent_os_id="my-os", resource="agents", resource_id="web-agent", action="read")

        >>> parse_scope("agent-os:my-os:agents:*:run")
        ParsedScope(raw="...", scope_type="agent-os", agent_os_id="my-os", resource="agents", resource_id="*", action="run", is_wildcard_resource=True)
    """
    if scope == "admin":
        return ParsedScope(raw=scope, scope_type="admin")

    parts = scope.split(":")

    # All valid scopes must start with "agent-os"
    if len(parts) < 4 or parts[0] != "agent-os":
        # Invalid format
        return ParsedScope(raw=scope, scope_type="unknown")

    agent_os_id = parts[1]
    is_wildcard_os = agent_os_id == "*"

    # Global resource scope: agent-os:<id>:resource:action (4 parts)
    if len(parts) == 4:
        return ParsedScope(
            raw=scope,
            scope_type="agent-os",
            agent_os_id=agent_os_id,
            resource=parts[2],
            action=parts[3],
            is_wildcard_os=is_wildcard_os,
        )

    # Per-resource scope: agent-os:<id>:resource:<resource-id>:action (5 parts)
    if len(parts) == 5:
        resource_id = parts[3]
        is_wildcard_resource = resource_id == "*"
        
        return ParsedScope(
            raw=scope,
            scope_type="agent-os",
            agent_os_id=agent_os_id,
            resource=parts[2],
            resource_id=resource_id,
            action=parts[4],
            is_wildcard_os=is_wildcard_os,
            is_wildcard_resource=is_wildcard_resource,
        )

    # Invalid format
    return ParsedScope(raw=scope, scope_type="unknown")


def matches_scope(
    user_scope: ParsedScope,
    required_scope: ParsedScope,
    agent_os_id: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> bool:
    """
    Check if a user's scope matches a required scope.

    Args:
        user_scope: The user's parsed scope
        required_scope: The required parsed scope
        agent_os_id: The current AgentOS instance ID
        resource_id: The specific resource ID being accessed

    Returns:
        True if the user's scope satisfies the required scope

    Examples:
        >>> user = parse_scope("agent-os:my-os:system:read")
        >>> required = parse_scope("agent-os:my-os:system:read")
        >>> matches_scope(user, required, agent_os_id="my-os")
        True

        >>> user = parse_scope("agent-os:*:agents:read")
        >>> required = parse_scope("agent-os:my-os:agents:read")
        >>> matches_scope(user, required, agent_os_id="my-os")
        True

        >>> user = parse_scope("agent-os:my-os:agents:web-agent:run")
        >>> required = parse_scope("agent-os:my-os:agents:<id>:run")
        >>> matches_scope(user, required, agent_os_id="my-os", resource_id="web-agent")
        True

        >>> user = parse_scope("agent-os:my-os:agents:*:run")
        >>> required = parse_scope("agent-os:my-os:agents:<id>:run")
        >>> matches_scope(user, required, agent_os_id="my-os", resource_id="web-agent")
        True
    """
    # Admin always matches
    if user_scope.scope_type == "admin":
        return True

    # Both must be agent-os scopes
    if not user_scope.is_agent_os_scope or not required_scope.is_agent_os_scope:
        return False

    # Check agent-os ID matches (or wildcard)
    if not user_scope.is_wildcard_os and user_scope.agent_os_id != agent_os_id:
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
    agent_os_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> bool:
    """
    Check if user has all required scopes.

    Args:
        user_scopes: List of scope strings the user has
        required_scopes: List of scope strings required (with <id> placeholders)
        agent_os_id: Current AgentOS instance ID
        resource_type: Type of resource being accessed ("agents", "teams", "workflows")
        resource_id: Specific resource ID being accessed

    Returns:
        True if user has all required scopes

    Examples:
        >>> has_required_scopes(
        ...     ["agent-os:my-os:agents:read"],
        ...     ["agents:read"],  # Template
        ...     agent_os_id="my-os"
        ... )
        True

        >>> has_required_scopes(
        ...     ["agent-os:my-os:agents:web-agent:run"],
        ...     ["agents:run"],  # Template
        ...     agent_os_id="my-os",
        ...     resource_type="agents",
        ...     resource_id="web-agent"
        ... )
        True

        >>> has_required_scopes(
        ...     ["agent-os:*:agents:*:run"],
        ...     ["agents:run"],  # Template
        ...     agent_os_id="any-os",
        ...     resource_type="agents",
        ...     resource_id="any-agent"
        ... )
        True
    """
    if not required_scopes:
        return True

    # Parse user scopes once
    parsed_user_scopes = [parse_scope(scope) for scope in user_scopes]

    # Check for admin scope
    if any(s.scope_type == "admin" for s in parsed_user_scopes):
        return True

    # Check each required scope
    for required_scope_str in required_scopes:
        # Convert template scope to full scope
        # E.g., "agents:read" -> "agent-os:<id>:agents:read"
        # E.g., "agents:run" -> "agent-os:<id>:agents:<resource-id>:run" (for resource-specific)
        
        parts = required_scope_str.split(":")
        if len(parts) == 2:
            resource, action = parts
            # Build the required scope based on context
            if resource_id and resource_type:
                # Per-resource scope required
                full_required_scope = f"agent-os:<id>:{resource_type}:<resource-id>:{action}"
            else:
                # Global resource scope required
                full_required_scope = f"agent-os:<id>:{resource}:{action}"
            
            required = parse_scope(full_required_scope)
        else:
            required = parse_scope(required_scope_str)

        scope_matched = False
        for user_scope in parsed_user_scopes:
            if matches_scope(user_scope, required, agent_os_id=agent_os_id, resource_id=resource_id):
                scope_matched = True
                break

        if not scope_matched:
            return False

    return True


def get_accessible_resource_ids(user_scopes: List[str], resource_type: str, agent_os_id: Optional[str] = None) -> Set[str]:
    """
    Get the set of resource IDs the user has access to.

    Args:
        user_scopes: List of scope strings the user has
        resource_type: Type of resource ("agents", "teams", "workflows")
        agent_os_id: Current AgentOS instance ID

    Returns:
        Set of resource IDs the user can access. Returns {"*"} for wildcard access.

    Examples:
        >>> get_accessible_resource_ids(
        ...     ["agent-os:my-os:agents:agent-1:read", "agent-os:my-os:agents:agent-2:read"],
        ...     "agents",
        ...     "my-os"
        ... )
        {'agent-1', 'agent-2'}

        >>> get_accessible_resource_ids(["agent-os:my-os:agents:*:read"], "agents", "my-os")
        {'*'}

        >>> get_accessible_resource_ids(["agent-os:my-os:agents:read"], "agents", "my-os")
        {'*'}

        >>> get_accessible_resource_ids(["admin"], "agents")
        {'*'}
    """
    parsed_scopes = [parse_scope(scope) for scope in user_scopes]

    # Check for admin or global wildcard access
    for scope in parsed_scopes:
        if scope.scope_type == "admin":
            return {"*"}

        if scope.is_agent_os_scope:
            # Check if OS ID matches (or is wildcard)
            if scope.is_wildcard_os or scope.agent_os_id == agent_os_id:
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
        if scope.is_agent_os_scope:
            # Check if OS ID matches (or is wildcard)
            if scope.is_wildcard_os or scope.agent_os_id == agent_os_id:
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

    Note: These are template scopes in simplified format (resource:action).
    The has_required_scopes() function converts them to full agent-os namespaced format:
    - "agents:read" → "agent-os:<os-id>:agents:read"
    - "agents:run" → "agent-os:<os-id>:agents:<agent-id>:run" (when resource_id provided)
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
