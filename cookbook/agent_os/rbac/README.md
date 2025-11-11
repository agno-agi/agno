# AgentOS JWT Authentication and RBAC Examples

This directory contains examples demonstrating JWT authentication and optional RBAC (Role-Based Access Control) in AgentOS.

## Overview

The `JWTMiddleware` in AgentOS provides:
1. **JWT Authentication**: Extracts and validates JWT tokens from requests
2. **Optional RBAC**: Opt-in scope-based authorization (disabled by default)

RBAC is **opt-in** - when `authorization=False` (default), the middleware only validates JWT tokens and stores claims in `request.state`. When `authorization=True` is provided, RBAC is enabled and endpoints are protected with scope checks.

## Features

- **JWT Authentication**: Secure token-based authentication
- **Optional Scope-Based Authorization**: Fine-grained permissions (opt-in via `scope_mappings`)
- **Middleware Protection**: Automatic enforcement across all endpoints
- **Custom Scope Mappings**: Define your own permission structure
- **Wildcard Scopes**: Use wildcards like `agents:*` for broader permissions
- **Admin Override**: Special `admin` scope grants full access

## Examples

### 1. Basic RBAC (`basic.py`)

Demonstrates enabling RBAC with default scope mappings.

**Features:**
- Enable RBAC by providing `authorization=True`
- Default scope mappings for all AgentOS endpoints
- Test tokens for different users

**Run:**
```bash
python cookbook/agent_os/rbac/basic.py
```

### 2. Custom Scope Mappings (`custom_scope_mappings.py`)

Shows how to define custom scopes for your application's specific needs.

**Features:**
- Custom permission structure
- Multiple scopes per endpoint
- Different permission levels (basic user, power user, admin)

**Run:**
```bash
python cookbook/agent_os/rbac/custom_scope_mappings.py
```

### 3. RBAC with Cookie (`with_cookie.py`)

Shows how to enable RBAC with cookie-based authentication.

**Features:**
- Cookie-based authentication
- Test tokens for different users

**Run:**
```bash
python cookbook/agent_os/rbac/with_cookie.py
```

## Default Scope Mappings

When you enable RBAC with `scope_mappings={}` (empty dict), these default scopes are applied:

### System Endpoints
- `GET /config` → `system:read`
- `GET /models` → `system:read`

### Agent Endpoints
- `GET /agents` → `agents:read`
- `GET /agents/*` → `agents:read`
- `POST /agents/*/runs` → `agents:run`
- `POST /agents/*/runs/*/continue` → `agents:run`
- `POST /agents/*/runs/*/cancel` → `agents:run`

### Team Endpoints
- `GET /teams` → `teams:read`
- `GET /teams/*` → `teams:read`
- `POST /teams/*/runs` → `teams:run`
- `POST /teams/*/runs/*/cancel` → `teams:run`

### Workflow Endpoints
- `GET /workflows` → `workflows:read`
- `GET /workflows/*` → `workflows:read`
- `POST /workflows/*/runs` → `workflows:run`
- `POST /workflows/*/runs/*/cancel` → `workflows:run`

### Session Endpoints
- `GET /sessions` → `sessions:read`
- `GET /sessions/*` → `sessions:read`
- `POST /sessions` → `sessions:write`
- `PATCH /sessions/*` → `sessions:write`
- `DELETE /sessions/*` → `sessions:delete`

### Memory Endpoints
- `GET /memories` → `memories:read`
- `POST /memories` → `memories:write`
- `PATCH /memories/*` → `memories:write`
- `DELETE /memories/*` → `memories:delete`

### Knowledge Endpoints
- `GET /knowledge/*` → `knowledge:read`
- `POST /knowledge/content` → `knowledge:write`
- `POST /knowledge/search` → `knowledge:read`
- `DELETE /knowledge/content` → `knowledge:delete`

### Metrics & Evaluation Endpoints
- `GET /metrics` → `metrics:read`
- `POST /metrics/refresh` → `metrics:write`
- `GET /eval-runs` → `evals:read`
- `POST /eval-runs` → `evals:write`

## Configuration Options

### Basic Configuration

```python
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware

# Option 1: Automatic JWT + RBAC (recommended)
agent_os = AgentOS(
    agents=[your_agent],
    authorization=True,
    authorization_secret="your-secret-key",
)
app = agent_os.get_app()
# JWT middleware with default scope mappings is automatically added!

# Option 2: Add custom scope mappings (additive to defaults)
agent_os = AgentOS(
    agents=[your_agent],
    authorization=True,
    authorization_secret="your-secret-key",
)
app = agent_os.get_app()

# Add custom JWT middleware with additional/override scope mappings
app.add_middleware(
    JWTMiddleware,
    secret_key="your-secret-key",
    authorization=True,
    scope_mappings={
        # Override default scope for existing endpoint
        "GET /agents": ["app:read"],
        # Add new custom endpoint
        "POST /custom/endpoint": ["app:execute"],
        # Allow access without scopes
        "GET /public": [],
    },
)
```

### Advanced Configuration (Manual Setup)

For advanced use cases, don't set authorization=True and configure manually:

```python
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware, TokenSource

agent_os = AgentOS(agents=[your_agent])
app = agent_os.get_app()

# Add JWT middleware with custom configuration
app.add_middleware(
    JWTMiddleware,
    # JWT configuration
    secret_key="your-secret-key",  # Or set JWT_SECRET_KEY env var
    algorithm="HS256",
    token_source=TokenSource.HEADER,  # HEADER, COOKIE, or BOTH
    token_header_key="X-API-Key",
    cookie_name="access_token",
    
    # JWT claim mapping
    user_id_claim="sub",
    session_id_claim="session_id",
    scopes_claim="scopes",
    
    # RBAC configuration
    authorization=True,  # Enable RBAC
    admin_scope="admin",  # Admin scope grants full access
    
    # Excluded routes (no JWT required)
    excluded_route_paths=[
        "/",
        "/health",
        "/docs",
    ],
)
```

## JWT Token Structure

Your JWT tokens should include these claims:

```json
{
  "sub": "user_123",           // User ID (extracted as request.state.user_id)
  "session_id": "session_456", // Session ID (extracted as request.state.session_id)
  "scopes": [                  // List of permission scopes (extracted as request.state.scopes)
    "agents:read",
    "agents:run",
    "sessions:write"
  ],
  "exp": 1234567890,           // Token expiration (Unix timestamp)
  "iat": 1234567800            // Issued at (Unix timestamp)
}
```

### Generating Test Tokens

```python
import jwt
from datetime import datetime, timedelta, UTC

def create_token(user_id: str, scopes: list[str]) -> str:
    payload = {
        "sub": user_id,
        "session_id": f"session_{user_id}",
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, "your-secret-key", algorithm="HS256")

# Create tokens for different users
admin_token = create_token("admin", ["admin"])
read_only_token = create_token("viewer", ["agents:read", "sessions:read"])
full_access_token = create_token("power_user", ["agents:*", "sessions:*"])
```

## Scope Mappings Behavior

### Additive Mappings

When you provide custom `scope_mappings`, they are **additive** to the default scope mappings:

- Default scope mappings are loaded first
- Your custom mappings are merged on top
- Conflicts are resolved by using your custom mapping
- Routes not in either mapping allow access (no scopes required)

**Example:**
```python
# This keeps all default mappings and adds/overrides specific ones
app.add_middleware(
    JWTMiddleware,
    secret_key="secret",
    authorization=True,
    scope_mappings={
        # Override: Change required scope for viewing agents
        "GET /agents": ["custom:view"],
        # Add new: Custom endpoint not in defaults
        "POST /custom/action": ["custom:execute"],
        # Allow: Explicitly allow without scopes
        "GET /public/stats": [],
    }
)
# All other default mappings (sessions, teams, etc.) still apply!
```

### Empty List Behavior

Use an empty list `[]` to explicitly allow access without requiring any scopes:

```python
scope_mappings={
    "GET /public/info": [],  # Any authenticated user can access
}
```

This is different from excluding a route via `excluded_route_paths`, which doesn't require JWT authentication at all.

## Wildcard Scopes

You can use wildcards:

- `agents:*` → Grants all agent permissions (`agents:read`, `agents:run`, etc.)
- `sessions:*` → Grants all session permissions
- `read:*` → Grants all read permissions across all resources
- `execute:*` → Grants all run/execute permissions

## Admin Scope

The `admin` scope (configurable via `admin_scope` parameter) bypasses all scope checks:

```python
app.add_middleware(
    JWTMiddleware,
    secret_key="your-secret-key",
    admin_scope="admin",
)
```

Users with the `admin` scope can access any endpoint, regardless of required scopes.

## Testing with cURL

```bash
# Generate token with specific scopes
TOKEN=$(python -c "import jwt; from datetime import datetime, timedelta, UTC; print(jwt.encode({'sub': 'user1', 'session_id': 'sess1', 'scopes': ['agents:read', 'agents:run'], 'exp': datetime.now(UTC) + timedelta(hours=1)}, 'your-secret-key', algorithm='HS256'))")

# List agents (requires agents:read)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/agents

# Run an agent (requires agents:run)
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "Hello"}' \
  http://localhost:8000/agents/my-agent/runs
```

## Error Responses

### 401 Unauthorized - Missing/Invalid Token
```json
{
  "detail": "Authentication required - no JWT token provided",
  "error_code": "MISSING_TOKEN"
}
```

```json
{
  "detail": "Invalid or expired JWT token",
  "error_code": "INVALID_TOKEN"
}
```

### 403 Forbidden - Insufficient Scopes
```json
{
  "detail": "Insufficient permissions",
  "error_code": "FORBIDDEN",
  "required_scopes": ["agents:run"]
}
```

## Best Practices

1. **Use Environment Variables**: Store your JWT secret key in environment variables:
   ```bash
   export JWT_SECRET_KEY="your-production-secret-key-at-least-256-bits"
   ```

2. **Start Simple**: Begin with JWT-only mode (`scope_mappings=None`), then add RBAC when needed

3. **Use Wildcard Scopes**: For development/internal tools, wildcards make permission management easier

4. **Short Expiration**: Set short token expiration times (1-24 hours) for security

