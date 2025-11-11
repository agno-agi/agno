"""AgentOS RBAC Scopes

This module defines all available permission scopes for AgentOS RBAC (Role-Based Access Control).
"""

from enum import Enum


class AgentOSScope(str, Enum):
    """
    Enum of all available AgentOS permission scopes.
    
    These scopes are used with JWT middleware to control access to AgentOS endpoints.
    Scopes follow the pattern: resource:action
    
    Special Scopes:
    - ADMIN: Grants full access to all endpoints
    
    Resource Scopes:
    - system:read - System configuration and model information
    - agents:read - List and view agents
    - agents:run - Execute agent runs
    - teams:read - List and view teams
    - teams:run - Execute team runs
    - workflows:read - List and view workflows
    - workflows:run - Execute workflow runs
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
    """
    
    # Special scopes
    ADMIN = "admin"
    
    # System scopes
    SYSTEM_READ = "system:read"
    
    # Agent scopes
    AGENTS_READ = "agents:read"
    AGENTS_RUN = "agents:run"
    
    # Team scopes
    TEAMS_READ = "teams:read"
    TEAMS_RUN = "teams:run"
    
    # Workflow scopes
    WORKFLOWS_READ = "workflows:read"
    WORKFLOWS_RUN = "workflows:run"
    
    # Session scopes
    SESSIONS_READ = "sessions:read"
    SESSIONS_WRITE = "sessions:write"
    SESSIONS_DELETE = "sessions:delete"
    
    # Memory scopes
    MEMORIES_READ = "memories:read"
    MEMORIES_WRITE = "memories:write"
    MEMORIES_DELETE = "memories:delete"
    
    # Knowledge scopes
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"
    KNOWLEDGE_DELETE = "knowledge:delete"
    
    # Metrics scopes
    METRICS_READ = "metrics:read"
    METRICS_WRITE = "metrics:write"
    
    # Evaluation scopes
    EVALS_READ = "evals:read"
    EVALS_WRITE = "evals:write"
    EVALS_DELETE = "evals:delete"


def get_scope_value(scope: AgentOSScope) -> str:
    """
    Get the string value of a scope.
    
    Args:
        scope: The AgentOSScope enum value
        
    Returns:
        The string value of the scope
        
    Example:
        >>> get_scope_value(AgentOSScope.AGENTS_READ)
        'agents:read'
    """
    return scope.value


def get_all_scopes() -> list[str]:
    """
    Get a list of all available scope strings.
    
    Returns:
        List of all scope string values
        
    Example:
        >>> scopes = get_all_scopes()
        >>> 'agents:read' in scopes
        True
    """
    return [scope.value for scope in AgentOSScope]

