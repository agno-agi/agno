# AgentOS RBAC - Role-Based Access Control

This directory contains examples demonstrating AgentOS's RBAC (Role-Based Access Control) system with JWT authentication.

## Overview

AgentOS RBAC provides fine-grained access control using JWT tokens with scopes. **ALL scopes use the agent-os namespace format** for consistency and multi-tenancy support.

The system supports:

1. **Global Resource Scopes** - OS-wide permissions for all resources
2. **Per-Resource Scopes** - Granular agent/team/workflow permissions
3. **Wildcard Support** - Flexible permission patterns at OS and resource level

## JWT Signing Algorithms

AgentOS supports both symmetric and asymmetric JWT signing:

| Algorithm | Type | Use Case |
|-----------|------|----------|
| **RS256** (default) | Asymmetric | Production - uses public/private key pairs |
| **HS256** | Symmetric | Development/testing - uses shared secret |

**Most examples in this directory use HS256 (symmetric) for simplicity.** This allows running examples without setting up key pairs. For production deployments, we recommend RS256 asymmetric keys.

For an asymmetric key example, see `basic_asymmetric.py` which demonstrates:
- RSA key pair generation
- Using private key to sign tokens (auth server)
- Using public key to verify tokens (AgentOS)

## Scope Format

**ALL scopes use the agent-os namespace:**

### 1. Admin Scope (Highest Privilege)
```
admin
```
Grants full access to all endpoints and resources.

### 2. Global Resource Scopes
Format: `agent-os:<agent-os-id>:resource:action`

Examples:
```
agent-os:my-os:system:read       # Read system configuration
agent-os:my-os:agents:read       # List all agents in this OS
agent-os:my-os:teams:read        # List all teams in this OS
agent-os:my-os:workflows:read    # List all workflows in this OS
agent-os:*:agents:read           # List agents from ANY OS (wildcard OS ID)
```

### 3. Per-Resource Scopes  
Format: `agent-os:<agent-os-id>:resource:<resource-id>:action`

Examples:
```
agent-os:my-os:agents:my-agent:read              # Read specific agent
agent-os:my-os:agents:my-agent:run               # Run specific agent
agent-os:my-os:agents:*:run                      # Run any agent in this OS (wildcard resource)
agent-os:my-os:teams:my-team:read                # Read specific team
agent-os:my-os:teams:*:run                       # Run any team in this OS
agent-os:*:agents:*:run                          # Run ANY agent in ANY OS (double wildcard)
```

## Scope Hierarchy

The system checks scopes in this order:

1. **Admin scope** - Grants all permissions
2. **Wildcard scopes** - Matches patterns like `agent:*:run` or `agent-os:*:agents:read`
3. **Specific scopes** - Exact matches for resources and actions

## Endpoint Filtering

### GET Endpoints (Automatic Filtering)

List endpoints automatically filter results based on user scopes:

- **GET /agents** - Only returns agents the user has access to
- **GET /teams** - Only returns teams the user has access to
- **GET /workflows** - Only returns workflows the user has access to

**Examples:**
```python
# User with specific agent scopes:
# ["agent-os:my-os:agents:agent-1:read", "agent-os:my-os:agents:agent-2:read"]
GET /agents → Returns only agent-1 and agent-2

# User with wildcard resource scope:
# ["agent-os:my-os:agents:*:read"]
GET /agents → Returns all agents in my-os

# User with global resource scope:
# ["agent-os:my-os:agents:read"]
GET /agents → Returns all agents in my-os

# User with wildcard OS scope:
# ["agent-os:*:agents:read"]
GET /agents → Returns all agents in any OS

# User with admin:
# ["admin"]
GET /agents → Returns all agents
```

### POST Endpoints (Access Checks)

Run endpoints check for matching scopes with resource context:

- **POST /agents/{agent_id}/runs** - Requires agent-os scope with agents:run for this agent
- **POST /teams/{team_id}/runs** - Requires agent-os scope with teams:run for this team
- **POST /workflows/{workflow_id}/runs** - Requires agent-os scope with workflows:run for this workflow

**Valid scope patterns for running agent "web-agent" in OS "my-os":**
- `agent-os:my-os:agents:web-agent:run` (specific agent)
- `agent-os:my-os:agents:*:run` (any agent in this OS)
- `agent-os:*:agents:*:run` (any agent in any OS)
- `admin` (full access)

## Examples

### Basic RBAC (Symmetric)
See `basic_symmetric.py` for a simple example using HS256 symmetric keys.

### Basic RBAC (Asymmetric) 
See `basic_asymmetric.py` for RS256 asymmetric key example (recommended for production).

### Per-Agent Permissions
See `agent_permissions.py` for custom scope mappings per agent.

### Advanced Scopes
See `advanced_scopes.py` for comprehensive examples of:
- Agent-OS namespaced scopes
- Per-resource scopes
- Wildcard patterns
- Multiple permission levels

## Quick Start

### 1. Enable RBAC

```python
from agno.os import AgentOS

agent_os = AgentOS(
    id="my-os",  # Important: Set ID for namespaced scopes
    agents=[agent1, agent2],
    authorization=True,  # Enable RBAC
    jwt_verification_key="your-public-key-or-secret",  # Or set JWT_VERIFICATION_KEY env var
    jwt_algorithm="RS256",  # Default; use "HS256" for symmetric keys
)

app = agent_os.get_app()
```

### 2. Create JWT Tokens with Scopes

```python
import jwt
from datetime import datetime, timedelta, UTC

# Admin user
admin_token = jwt.encode({
    "sub": "admin_user",
    "scopes": ["admin"],
    "exp": datetime.now(UTC) + timedelta(hours=24),
}, "your-secret", algorithm="HS256")

# Power user (OS-wide access to all agents)
power_user_token = jwt.encode({
    "sub": "power_user",
    "scopes": [
        "agent-os:my-os:agents:read",     # List all agents
        "agent-os:my-os:agents:*:run",    # Run any agent
    ],
    "exp": datetime.now(UTC) + timedelta(hours=24),
}, "your-secret", algorithm="HS256")

# Limited user (specific agents only)
limited_token = jwt.encode({
    "sub": "limited_user",
    "scopes": [
        "agent-os:my-os:agents:agent-1:read",
        "agent-os:my-os:agents:agent-1:run",
    ],
    "exp": datetime.now(UTC) + timedelta(hours=24),
}, "your-secret", algorithm="HS256")
```

### 3. Make Authenticated Requests

```bash
# List agents (filtered by scopes)
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:7777/agents

# Run specific agent
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "message=Hello" \
  http://localhost:7777/agents/agent-1/runs
```

## Default Scope Mappings

All AgentOS endpoints have default scope requirements:

```python
{
    # System
    "GET /config": ["system:read"],
    "GET /models": ["system:read"],
    
    # Agents
    "GET /agents": ["agents:read"],
    "GET /agents/*": ["agents:read"],
    "POST /agents/*/runs": ["agents:run"],
    
    # Teams
    "GET /teams": ["teams:read"],
    "POST /teams/*/runs": ["teams:run"],
    
    # Workflows
    "GET /workflows": ["workflows:read"],
    "POST /workflows/*/runs": ["workflows:run"],
    
    # Sessions
    "GET /sessions": ["sessions:read"],
    "POST /sessions": ["sessions:write"],
    "DELETE /sessions/*": ["sessions:delete"],
    
    # And more...
}
```

## Custom Scope Mappings

You can override or extend default mappings:

```python
from agno.os.middleware import JWTMiddleware

app.add_middleware(
    JWTMiddleware,
    verification_key="your-public-key-or-secret",
    algorithm="RS256",  # Default; use "HS256" for symmetric keys
    authorization=True,
    scope_mappings={
        # Override default
        "GET /agents": ["custom:scope"],
        
        # Add new endpoint
        "POST /custom/endpoint": ["custom:action"],
        
        # Allow without scopes
        "GET /public": [],
    }
)
```

## Security Best Practices

1. **Use RS256 asymmetric keys in production** - Only share the public key with AgentOS
2. **Use environment variables** for keys and secrets
3. **Use PostgreSQL in production** (not SQLite)
4. **Set appropriate token expiration** (exp claim)
5. **Use HTTPS** in production
6. **Rotate keys regularly**
7. **Follow principle of least privilege** - Grant minimum required scopes
8. **Monitor access logs** for suspicious activity
9. **Use agent-os namespacing** for multi-tenant deployments

## Troubleshooting

### 401 Unauthorized
- Token missing or expired
- Invalid JWT secret
- Token format incorrect

### 403 Forbidden
- User lacks required scopes
- Agent-OS ID mismatch
- Resource not accessible with user's scopes

### Agents not appearing in GET /agents
- User lacks read scopes for those agents
- Check both `agent-os:*:agents:read` and `agent:<id>:read` scopes

## Additional Resources

- [AgentOS Documentation](https://docs.agno.com)
- [JWT.io](https://jwt.io) - JWT debugging tool
- [RFC 7519](https://tools.ietf.org/html/rfc7519) - JWT specification
