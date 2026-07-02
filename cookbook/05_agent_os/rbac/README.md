# AgentOS RBAC - Role-Based Access Control

This directory contains examples demonstrating AgentOS's RBAC (Role-Based Access Control) system with JWT authentication.

## Overview

AgentOS RBAC provides fine-grained access control using JWT tokens with scopes.

**Important:** RBAC is opt-in. Router-level authorization checks (scope validation, resource filtering) only run when `authorization=True` is set on the JWT middleware. Without this flag, JWT tokens are validated but all resources are accessible.

The system supports:

1. **Global Resource Scopes** - Permissions for all resources of a type
2. **Per-Resource Scopes** - Granular agent/team/workflow permissions
3. **Wildcard Support** - Flexible permission patterns
4. **Audience Verification** - JWT `aud` claim must match the AgentOS ID

## AgentOS Control Plane

RBAC on AgentOS is compatible with the AgentOS Control Plane. When connecting your AgentOS, you'll need to enable "Authorization" for traffic from the control plane to have the required JWT token with the correct scopes.

See the [documentation](https://docs.agno.com/agent-os/security/overview) for more information about AgentOS Security.

Note: Only Asymmetric keys are supported for AgentOS Control Plane traffic.  The public key will be provided by the control plane when you connect your AgentOS.

## JWT Signing Algorithms

AgentOS supports both symmetric and asymmetric JWT signing:

| Algorithm | Type | Use Case |
|-----------|------|----------|
| **RS256** (default) | Asymmetric | Production - uses public/private key pairs |
| **HS256** | Symmetric | Development/testing - uses shared secret |

**Most examples in this directory use HS256 (symmetric) for simplicity.** This allows running examples without setting up key pairs. For production deployments, we recommend RS256 asymmetric keys.

For an asymmetric key example, see `asymmetric/basic.py` which demonstrates:
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

When `verify_audience=True`, tokens with a mismatched `aud` claim will be rejected with a 401 error.

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
config:read       # Read OS configuration (legacy alias: system:read)
registry:read     # Read the code-defined registry
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
See `symmetric/basic.py` for a simple example using HS256 symmetric keys.

### Basic RBAC (Asymmetric) 
See `asymmetric/basic.py` for RS256 asymmetric key example (recommended for production).

### Per-Agent Permissions
See `symmetric/agent_permissions.py` for custom scope mappings per agent.

### Advanced Scopes
See `symmetric/advanced_scopes.py` for comprehensive examples of:
- Global and per-resource scopes
- Wildcard patterns
- Multiple permission levels
- Audience verification

## Quick Start

### 1. Enable RBAC

There are two ways to enable RBAC:

**Option A: Via AgentOS parameters (recommended)**
```python
from agno.os import AgentOS

agent_os = AgentOS(
    id="my-agent-os",
    agents=[agent1, agent2],
    authorization=True,  # Enable RBAC
    authorization_config=AuthorizationConfig(
        verification_keys=["your-public-key-or-secret"],  # Or set JWT_VERIFICATION_KEY env var
        algorithm="RS256",  # Default; use "HS256" for symmetric keys
    ),
)

app = agent_os.get_app()
```

**Option B: Via JWTMiddleware directly**
```python
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware

agent_os = AgentOS(
    id="my-agent-os",
    agents=[agent1, agent2],
)

app = agent_os.get_app()

app.add_middleware(
    JWTMiddleware,
    verification_keys=["your-public-key-or-secret"],
    algorithm="RS256",
    authorization=True,  # Enable RBAC - without this, scopes are NOT enforced
)
```

**Note:** When `authorization=False` (or not set), JWT tokens are still validated but scope-based access control is disabled - all authenticated users can access all resources.

### 2. Create JWT Tokens with Scopes and Audience

```python
import jwt
from datetime import datetime, timedelta, UTC

# Admin user
admin_token = jwt.encode({
    "sub": "admin_user",
    "aud": "my-agent-os",
    "scopes": ["agent_os:admin"],
    "exp": datetime.now(UTC) + timedelta(hours=24),
}, "your-secret", algorithm="HS256")

# Power user (global access to all agents)
power_user_token = jwt.encode({
    "sub": "power_user",
    "aud": "my-agent-os",
    "scopes": [
        "agents:read",     # List all agents
        "agents:*:run",    # Run any agent
    ],
    "exp": datetime.now(UTC) + timedelta(hours=24),
}, "your-secret", algorithm="HS256")

# Limited user (specific agents only)
limited_token = jwt.encode({
    "sub": "limited_user",
    "aud": "my-agent-os",
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
    # Config (legacy alias: system:read)
    "GET /config": ["config:read"],
    "GET /models": ["config:read"],
    "GET /registry": ["registry:read"],
    
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

See `/libs/agno/agno/os/scopes.py` for the default scope mappings.

## Custom Scope Mappings

You can override or extend default mappings:

```python
from agno.os.middleware import JWTMiddleware

app.add_middleware(
    JWTMiddleware,
    verification_keys=["your-public-key-or-secret"],
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

1. **Use RS256 asymmetric keys in production** - Only share the public key with AgentOS. This is how the AgentOS Control Plane communicates with your AgentOS instance.
2. **Use environment variables** for keys and secrets
3. **Set appropriate token expiration** (exp claim)
4. **Use HTTPS** in production
5. **Follow principle of least privilege** - Grant minimum required scopes
6. **Monitor access logs** for suspicious activity

## Troubleshooting

### 401 Unauthorized
- Token missing or expired
- Invalid JWT secret/key
- Token format incorrect

### 403 Forbidden
- User lacks required scopes
- Resource not accessible with user's scopes

### Agents not appearing in GET /agents
- User lacks read scopes for those agents
- Check both `agents:read` and `agents:<id>:read` scopes

### Scopes not being enforced
- Ensure `authorization=True` is set on JWTMiddleware or AgentOS
- Without this flag, JWT validation occurs but scope checks are skipped
- All authenticated users will have access to all resources

## Pluggable authorization providers (experimental)

The default scope matcher above is one implementation of a swappable seam:
`AuthorizationConfig(authorization_provider=...)`. Supply your own
`AuthorizationProvider` to change the decision engine without touching the
request pipeline. Two enforcement points (the middleware route gate and the
per-resource handler check) both go through it.

### The three tiers (a ladder - pick the lowest that fits)

Each tier is a strict superset of the one below it: you only climb when you hit
the previous tier's ceiling. All three plug into the *same* seam
(`AuthorizationConfig`) and the *same* two enforcement points, so moving up a tier
changes only what you pass in - not your app.

| Tier | When to use it | What it adds over the tier below | You write | Dependency |
|------|----------------|----------------------------------|-----------|------------|
| **1. Scope-based RBAC** (default `ScopeAuthorizationProvider`) | Permissions are known at token-mint time and rarely change; whoever issues tokens can put scopes on them. The simplest thing that works. | — (the baseline) | scopes in the JWT (`agents:*:read`, `agents:research-agent:run`, `agent_os:admin`) | none |
| **2. Managed roles** (`ManagedRoleStore`) | You want to define/assign roles yourself and change them at runtime without re-minting tokens, and keep the policy in your own DB. | **Runtime-mutable** roles + per-resource scopes + **deny** rules + **agent-aware change audit** (who changed what), all **persisted** and read fresh per request (no stale cache, consistent across replicas). | `store.set_role_scopes(...)` / `store.assign(...)` in agno scope terms | `agno[roles]` (agno's native engine, no third-party) |
| **3. Custom / external provider** | Your model isn't scopes at all - ReBAC ("is this user an owner?"), ABAC ("same tenant?"), or role names that live in an external IdP / policy engine (OpenFGA, etc.). | Total control of the decision: any model, any backend. agno still owns the request pipeline + the two enforcement points. | your own `AuthorizationProvider` (implement `check` / `accessible_resource_ids`, optionally `authorize_route`) | yours |

**Why managed roles even when your IdP already has role names?** An IdP knows
*who* is a "member" or "admin"; it does not know what those words mean *inside your
AgentOS*. Tier 2 (or a tier-3 provider keyed off the IdP's `roles` claim) is where
**agno owns the per-resource scopes, the deny rules, and the decision audit** - the
mapping from "admin" to "may run research-agent but not delete sessions" lives with
your app, not in the IdP. `idp_workos_auth0.py` shows exactly this split.

Each cookbook below runs the whole scenario for you and prints a plain
`ALLOWED` / `BLOCKED` transcript that explains itself, then exits (no server, no
curl needed). Every file starts with a short plain-English explainer at the top.

New to authorization? Read them in this order — each is runnable on its own:

1. `managed_roles.py` — **start here (Tier 2).** What roles are, and how handing
   someone a role decides what they can do. Shows a change taking effect instantly
   (no re-login). Wired with the preferred `AuthorizationConfig(role_store=store)`
   shortcut; the constructor params are documented inline at the call site.
2. `managed_roles_sessions.py` — roles protecting real data: who may delete a saved
   chat session (and who is stopped before any data is touched).
3. `managed_roles_audit.py` — the governance angle: the two append-only trails
   (who changed what, and every allow/deny), turned on with a `DbAuditSink`.
4. `custom_authorization_provider.py` — **Tier 3, minimal.** The smallest possible
   custom `AuthorizationProvider`: a `tier` claim drives a non-scope decision model.
   Implement the ABC (`check` / `accessible_resource_ids`), wire it via
   `AuthorizationConfig(authorization_provider=...)`. Start here for the custom path.
5. `idp_workos_auth0.py` — **Tier 3, production-shaped.** They already have a login
   service (WorkOS/Auth0/Okta): the role rides the token, you only enforce, via a
   ~30-line custom `AuthorizationProvider`. Adds JWKS verification + issuer/audience
   pinning. (Enforcement only — no user store needed.)

This covers the ways a company runs authorization:

| Their situation | Tier | Who owns "who has which role" | Cookbook |
|---|---|---|---|
| Scopes are on the token already | 1 | the token issuer (scopes claim) | `symmetric/`, `asymmetric/` |
| No login service; we define + assign roles | 2 | us, in the managed store | `managed_roles.py` |
| They have a login service; we only enforce | 3 | the login service (role on the token) | `idp_workos_auth0.py` |
| You want a custom decision model (ReBAC/ABAC/own engine) | 3 | you (your own `AuthorizationProvider`) | `custom_authorization_provider.py` (minimal), `idp_workos_auth0.py` (IdP-shaped) |

For symmetric/asymmetric JWT basics (the default scope tier, no roles) see
`symmetric/` and `asymmetric/`. The **user directory** (storing users, the
`/authz/users` admin API, the single-file admin console) and **ReBAC/FGA** are the
next layer — see the directory and FGA PRs.

Install the optional extra for DB-backed persistence: `pip install "agno[roles]"`.

## Additional Resources

- [AgentOS Documentation](https://docs.agno.com/agent-os/security/overview)
- [JWT.io](https://jwt.io) - JWT debugging tool
