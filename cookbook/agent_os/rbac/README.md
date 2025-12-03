# AgentOS RBAC - Role-Based Access Control

This directory contains examples demonstrating AgentOS's RBAC (Role-Based Access Control) system with JWT authentication.

## Overview

AgentOS RBAC provides fine-grained access control using JWT tokens with scopes.

The system supports:

1. **Audience Verification** - JWT `aud` claim must match the AgentOS ID
2. **Global Resource Scopes** - Permissions for all resources of a type
3. **Per-Resource Scopes** - Granular agent/team/workflow permissions
4. **Wildcard Support** - Flexible permission patterns

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

## Audience Verification

The `aud` (audience) claim in JWT tokens is used to verify the token is intended for this AgentOS instance:

```python
# Token payload must include aud claim matching AgentOS ID
payload = {
    "sub": "user_123",
    "aud": "my-agent-os",  # Must match AgentOS ID
    "scopes": ["agents:read", "agents:run"],
    "exp": datetime.now(UTC) + timedelta(hours=24),
}
```

When `verify_audience=True` (default when authorization is enabled), tokens with a mismatched `aud` claim will be rejected with a 401 error.

## Scope Format

### 1. Admin Scope (Highest Privilege)
```
agent_os:admin
```
Grants full access to all endpoints and resources.

### 2. Global Resource Scopes
Format: `resource:action`

Examples:
```
system:read       # Read system configuration
agents:read       # List all agents
agents:run        # Run any agent
teams:read        # List all teams
workflows:read    # List all workflows
```

### 3. Per-Resource Scopes  
Format: `resource:<resource-id>:action`

Examples:
```
agents:my-agent:read              # Read specific agent
agents:my-agent:run               # Run specific agent
agents:*:run                      # Run any agent (wildcard)
teams:my-team:read                # Read specific team
teams:*:run                       # Run any team (wildcard)
```

## Scope Hierarchy

The system checks scopes in this order:

1. **Admin scope** - Grants all permissions
2. **Wildcard scopes** - Matches patterns like `agents:*:run`
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
# ["agents:agent-1:read", "agents:agent-2:read"]
GET /agents -> Returns only agent-1 and agent-2

# User with wildcard resource scope:
# ["agents:*:read"]
GET /agents -> Returns all agents

# User with global resource scope:
# ["agents:read"]
GET /agents -> Returns all agents

# User with admin:
# ["agent_os:admin"]
GET /agents -> Returns all agents
```

### POST Endpoints (Access Checks)

Run endpoints check for matching scopes with resource context:

- **POST /agents/{agent_id}/runs** - Requires agents scope with run action
- **POST /teams/{team_id}/runs** - Requires teams scope with run action
- **POST /workflows/{workflow_id}/runs** - Requires workflows scope with run action

**Valid scope patterns for running agent "web-agent":**
- `agents:web-agent:run` (specific agent)
- `agents:*:run` (any agent - wildcard)
- `agents:run` (global scope)
- `agent_os:admin` (full access)

## Examples

### Basic RBAC (Symmetric)
See `basic_symmetric.py` for a simple example using HS256 symmetric keys.

### Basic RBAC (Asymmetric) 
See `basic_asymmetric.py` for RS256 asymmetric key example (recommended for production).

### Per-Agent Permissions
See `agent_permissions.py` for custom scope mappings per agent.

### Advanced Scopes
See `advanced_scopes.py` for comprehensive examples of:
- Global and per-resource scopes
- Wildcard patterns
- Multiple permission levels
- Audience verification

## Quick Start

### 1. Enable RBAC

```python
from agno.os import AgentOS

agent_os = AgentOS(
    id="my-agent-os",  # Important: Set ID for audience verification
    agents=[agent1, agent2],
    authorization=True,  # Enable RBAC
    jwt_verification_key="your-public-key-or-secret",  # Or set JWT_VERIFICATION_KEY env var
    jwt_algorithm="RS256",  # Default; use "HS256" for symmetric keys
)

app = agent_os.get_app()
```

### 2. Create JWT Tokens with Scopes and Audience

```python
import jwt
from datetime import datetime, timedelta, UTC

# Admin user
admin_token = jwt.encode({
    "sub": "admin_user",
    "aud": "my-agent-os",  # Must match AgentOS ID
    "scopes": ["agent_os:admin"],
    "exp": datetime.now(UTC) + timedelta(hours=24),
}, "your-secret", algorithm="HS256")

# Power user (global access to all agents)
power_user_token = jwt.encode({
    "sub": "power_user",
    "aud": "my-agent-os",  # Must match AgentOS ID
    "scopes": [
        "agents:read",     # List all agents
        "agents:*:run",    # Run any agent
    ],
    "exp": datetime.now(UTC) + timedelta(hours=24),
}, "your-secret", algorithm="HS256")

# Limited user (specific agents only)
limited_token = jwt.encode({
    "sub": "limited_user",
    "aud": "my-agent-os",  # Must match AgentOS ID
    "scopes": [
        "agents:agent-1:read",
        "agents:agent-1:run",
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
    verify_audience=True,  # Verify aud claim matches AgentOS ID
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
5. **Include audience claim** (aud) matching your AgentOS ID
6. **Use HTTPS** in production
7. **Rotate keys regularly**
8. **Follow principle of least privilege** - Grant minimum required scopes
9. **Monitor access logs** for suspicious activity

## Troubleshooting

### 401 Unauthorized
- Token missing or expired
- Invalid JWT secret/key
- Token format incorrect
- **Audience mismatch** - `aud` claim doesn't match AgentOS ID

### 403 Forbidden
- User lacks required scopes
- Resource not accessible with user's scopes

### Agents not appearing in GET /agents
- User lacks read scopes for those agents
- Check both `agents:read` and `agents:<id>:read` scopes

## Additional Resources

- [AgentOS Documentation](https://docs.agno.com)
- [JWT.io](https://jwt.io) - JWT debugging tool
- [RFC 7519](https://tools.ietf.org/html/rfc7519) - JWT specification
