"""
Custom Scope Mappings Example

This example demonstrates how to define custom scope mappings for your AgentOS endpoints.
You can specify exactly which scopes are required for each endpoint.

Pre-requisites:
- Set JWT_VERIFICATION_KEY environment variable or pass it to middleware
- Endpoints are automatically protected with default scope mappings
"""

from datetime import UTC, datetime, timedelta
import os
import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.tools.duckduckgo import DuckDuckGoTools

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")

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
    description="Custom Scope Mappings AgentOS",
    agents=[research_agent],
)

app = agent_os.get_app()

# Add JWT middleware with RBAC enabled using custom scope mappings
app.add_middleware(
    JWTMiddleware,
    verification_key=JWT_SECRET,
    algorithm="HS256", # Use HS256 for symmetric key
    scope_mappings=custom_scopes,  # Providing scope_mappings enables RBAC
    admin_scope="admin",  # Admin can bypass all checks
    cors_allowed_origins=["http://localhost:3000"],
)

if __name__ == "__main__":
    """
    Run your AgentOS with custom scope mappings.
    
    This example shows how to:
    1. Define custom scopes for your application
    2. Require multiple scopes for sensitive operations
    3. Create different permission levels
    """

    # Create tokens with different permission levels
    basic_user_token = jwt.encode(
        {
            "sub": "user_123",
            "scopes": ["app:read"],  # Can only read, not execute
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    power_user_token = jwt.encode(
        {
            "sub": "user_456",
            "scopes": ["app:read", "app:run", "app:execute"],  # Can read and execute
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    admin_token = jwt.encode(
        {
            "sub": "admin_789",
            "scopes": ["admin"],  # Admin bypasses all checks
            "exp": datetime.now(UTC) + timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    print("\n" + "=" * 60)
    print("Custom Scope Mappings - Test Tokens")
    print("=" * 60)
    print("\nBasic User Token (app:read only):")
    print(basic_user_token)
    print("\nPower User Token (app:read, app:run, app:execute):")
    print(power_user_token)
    print("\nAdmin Token (admin - bypasses all checks):")
    print(admin_token)
    print("\n" + "=" * 60)
    print("\nTest commands:")
    print("\n# Basic user can read agents:")
    print(
        f'curl -H "Authorization: Bearer {basic_user_token}" http://localhost:7777/agents'
    )
    print("\n# But cannot run them (missing app:run and app:execute):")
    print(
        f'curl -X POST -H "Authorization: Bearer {basic_user_token}" '
        f'-H "Content-Type: application/json" '
        f'-d \'{{"message": "test"}}\' '
        f"http://localhost:7777/agents/research-agent/runs"
    )
    print("\n# Power user can do both:")
    print(
        f'curl -X POST -H "Authorization: Bearer {power_user_token}" '
        f'-H "Content-Type: application/json" '
        f'-d \'{{"message": "test"}}\' '
        f"http://localhost:7777/agents/research-agent/runs"
    )
    print("\n" + "=" * 60 + "\n")

    agent_os.serve(app="custom_scope_mappings:app", port=7777, reload=True)
