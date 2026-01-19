"""
Custom Scope Mappings Example

This example demonstrates how to define custom scope mappings for your AgentOS endpoints.
You can specify exactly which scopes are required for each endpoint.

RS256 uses:
- Private key: Used by your auth server to SIGN tokens
- Public key: Used by AgentOS to VERIFY token signatures

Pre-requisites:
- Set JWT_SIGNING_KEY and JWT_VERIFICATION_KEY environment variables with your public and private keys (PEM format)
- Or generate keys at runtime for testing (as shown below)
- Endpoints are automatically protected with default scope mappings
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.cryptography import generate_rsa_keys

# Keys file path for persistence across reloads
_KEYS_FILE = "/tmp/agno_rbac_demo_keys.json"


def _load_or_generate_keys():
    """Load keys from file or generate new ones. Persists keys for reload consistency."""
    import json

    # First check environment variables
    public_key = os.getenv("JWT_VERIFICATION_KEY", None)
    private_key = os.getenv("JWT_SIGNING_KEY", None)

    if public_key and private_key:
        return private_key, public_key

    # Try to load from file (for reload consistency)
    if os.path.exists(_KEYS_FILE):
        with open(_KEYS_FILE, "r") as f:
            keys = json.load(f)
            return keys["private_key"], keys["public_key"]

    # Generate new keys and save them
    private_key, public_key = generate_rsa_keys()
    with open(_KEYS_FILE, "w") as f:
        json.dump({"private_key": private_key, "public_key": public_key}, f)

    return private_key, public_key


PRIVATE_KEY, PUBLIC_KEY = _load_or_generate_keys()

# Setup database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Create agents
research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    markdown=True,
)

# Define custom scope mappings
# Format: "METHOD /path": ["scope1", "scope2"]
custom_scopes = {
    "GET /config": ["app:admin"],
    # Agent endpoints
    "GET /agents": ["app:read"],  # Custom scope instead of default "agents:read"
    "GET /agents/*": ["app:read"],
    "POST /agents/*/runs": ["app:run", "app:execute"],  # Require both scopes
    # Session endpoints
    "GET /sessions": ["app:admin"],  # Only admins can view sessions
    "GET /sessions/*": ["app:read", "sessions:read"],
    # Memory endpoints
    "GET /memories": ["memory:admin"],
    "POST /memories": ["memory:write"],
}

# Create AgentOS
agent_os = AgentOS(
    id="my-agent-os",
    description="Custom Scope Mappings AgentOS",
    agents=[research_agent],
)

app = agent_os.get_app()

# Add JWT middleware with RBAC enabled using custom scope mappings
app.add_middleware(
    JWTMiddleware,
    verification_keys=[PUBLIC_KEY],
    algorithm="RS256",  # Use RS256 for asymmetric key
    scope_mappings=custom_scopes,  # Providing scope_mappings enables RBAC
    admin_scope="foo:bar",  # Admin can bypass all checks with this scope
)

if __name__ == "__main__":
    """
    Run your AgentOS with custom scope mappings.
    
    Audience Verification:
    - Tokens must include `aud` claim matching the AgentOS ID
    - Tokens with wrong audience will be rejected
    
    This example shows how to:
    1. Define custom scopes for your application
    2. Require multiple scopes for sensitive operations
    3. Create different permission levels
    """

    # Create tokens with different permission levels
    # Note: Include `aud` claim with AgentOS ID
    basic_user_token = jwt.encode(
        {
            "sub": "user_123",
            "scopes": ["app:read"],  # Can only read, not execute
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
        PRIVATE_KEY,
        algorithm="RS256",
    )

    power_user_token = jwt.encode(
        {
            "sub": "user_456",
            "scopes": ["app:read", "app:run", "app:execute"],  # Can read and execute
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
        PRIVATE_KEY,
        algorithm="RS256",
    )

    admin_token = jwt.encode(
        {
            "sub": "admin_789",
            "scopes": ["agent_os:admin"],  # Admin bypasses all checks
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
        PRIVATE_KEY,
        algorithm="RS256",
    )

    print("\n" + "=" * 60)
    print("Custom Scope Mappings - Test Tokens")
    print("=" * 60)
    print("\nBasic User Token (app:read only):")
    print(basic_user_token)
    print("\nPower User Token (app:read, app:run, app:execute):")
    print(power_user_token)
    print("\nAdmin Token (agent_os:admin - bypasses all checks):")
    print(admin_token)
    print("\n" + "=" * 60)
    print("\nTest commands:")
    print("\n# Basic user can read agents:")
    print(
        'curl -H "Authorization: Bearer '
        + basic_user_token
        + '" http://localhost:7777/agents'
    )
    print("\n# But cannot run them (missing app:run and app:execute):")
    print(
        'curl -X POST -H "Authorization: Bearer ' + basic_user_token + '" '
        '-H "Content-Type: application/json" '
        '-d \'{"message": "test"}\' '
        "http://localhost:7777/agents/research-agent/runs"
    )
    print("\n# Power user can do both:")
    print(
        'curl -X POST -H "Authorization: Bearer ' + power_user_token + '" '
        '-H "Content-Type: application/json" '
        '-d \'{"message": "test"}\' '
        "http://localhost:7777/agents/research-agent/runs"
    )
    print("\n" + "=" * 60 + "\n")

    agent_os.serve(app="custom_scope_mappings:app", port=7777, reload=True)
