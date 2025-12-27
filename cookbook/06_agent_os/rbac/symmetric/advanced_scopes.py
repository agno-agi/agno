"""
Advanced RBAC Example with AgentOS - Simplified Scopes with Audience Verification

This example demonstrates the AgentOS RBAC system with simplified scope format:

Scope Format:
1. Global resource scopes: resource:action
2. Per-resource scopes: resource:<resource-id>:action
3. Wildcard support: resource:*:action

Scope Examples:
- system:read - Read system config
- agents:read - List all agents
- agents:web-agent:read - Read specific agent
- agents:web-agent:run - Run specific agent
- agents:*:run - Run ANY agent (wildcard)
- agent_os:admin - Full access to everything

Prerequisites:
- Set JWT_VERIFICATION_KEY environment variable
- Endpoints automatically filter based on user scopes
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.tools.duckduckgo import DuckDuckGoTools

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")

# Setup database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Create agents with different capabilities
web_search_agent = Agent(
    id="web-search-agent",
    name="Web Search Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    markdown=True,
)

analyst_agent = Agent(
    id="analyst-agent",
    name="Data Analyst Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

admin_agent = Agent(
    id="admin-agent",
    name="Admin Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    markdown=True,
)


# Create AgentOS with specific ID for audience verification
agent_os = AgentOS(
    id="my-agent-os",
    name="Production AgentOS",
    description="RBAC Protected AgentOS with Simplified Scopes",
    agents=[web_search_agent, analyst_agent, admin_agent],
    authorization=True,  # Enable RBAC
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
    ),
)

# Get the app
app = agent_os.get_app()


def create_token(user_id: str, scopes: list[str], hours: int = 24) -> str:
    """Helper function to create JWT tokens with scopes and audience."""
    payload = {
        "sub": user_id,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=hours),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


if __name__ == "__main__":
    """
    Scope Hierarchy and Examples:
    
    1. ADMIN SCOPE (highest privilege):
       - "agent_os:admin" grants full access to all endpoints
    
    2. GLOBAL RESOURCE SCOPES:
       - "system:read" - Read system configuration
       - "agents:read" - List all agents
       - "agents:run" - Run any agent
    
    3. PER-RESOURCE SCOPES (granular permissions):
       - "agents:web-search-agent:read" - Read specific agent
       - "agents:web-search-agent:run" - Run specific agent
       - "agents:*:run" - Run ANY agent (wildcard)
    
    AUDIENCE VERIFICATION:
       - Tokens for other AgentOS instances will be rejected
    """

    # EXAMPLE 1: Admin user - full access
    admin_token = create_token(
        user_id="admin_user",
        scopes=["agent_os:admin"],
    )

    # EXAMPLE 2: Power user - can list and run all agents
    power_user_token = create_token(
        user_id="power_user",
        scopes=[
            "system:read",
            "agents:read",
            "agents:run",
            "sessions:read",
            "sessions:write",
        ],
    )

    # EXAMPLE 3: Limited user - can only run specific agents
    limited_user_token = create_token(
        user_id="limited_user",
        scopes=[
            "agents:web-search-agent:read",
            "agents:web-search-agent:run",
            "agents:analyst-agent:read",
            "agents:analyst-agent:run",
            # Note: This user won't see admin-agent in GET /agents
        ],
    )

    # EXAMPLE 4: Read-only user - can only view agents
    readonly_user_token = create_token(
        user_id="readonly_user",
        scopes=[
            "agents:*:read",  # Can read all agents
            "system:read",  # Can read system info
            # Cannot run any agents
        ],
    )

    # EXAMPLE 5: Wildcard user - can run any agent
    wildcard_user_token = create_token(
        user_id="wildcard_user",
        scopes=[
            "agents:read",  # Read all agents
            "agents:*:run",  # Run any agent (wildcard)
        ],
    )

    print("\n" + "=" * 80)
    print("ADVANCED RBAC TEST TOKENS")
    print("=" * 80)

    print("\n1. ADMIN USER (full access):")
    print("   Scopes: ['agent_os:admin']")
    print("   Token: " + admin_token[:50] + "...")

    print("\n2. POWER USER (global access):")
    print("   Scopes: ['system:read', 'agents:read', 'agents:run', ...]")
    print("   Token: " + power_user_token[:50] + "...")

    print("\n3. LIMITED USER (specific agents only):")
    print(
        "   Scopes: ['agents:web-search-agent:read', 'agents:web-search-agent:run', ...]"
    )
    print("   Token: " + limited_user_token[:50] + "...")

    print("\n4. READ-ONLY USER (view only):")
    print("   Scopes: ['agents:*:read', 'system:read']")
    print("   Token: " + readonly_user_token[:50] + "...")

    print("\n5. WILDCARD USER (run any agent):")
    print("   Scopes: ['agents:read', 'agents:*:run']")
    print("   Token: " + wildcard_user_token[:50] + "...")

    print("\n" + "=" * 80)
    print("TEST COMMANDS")
    print("=" * 80)

    print("\n# Test admin access (should work for all endpoints):")
    print(
        'curl -H "Authorization: Bearer '
        + admin_token
        + '" http://localhost:7777/agents'
    )
    print(
        'curl -H "Authorization: Bearer '
        + admin_token
        + '" http://localhost:7777/config'
    )

    print("\n# Test power user (should see all agents and run any):")
    print(
        'curl -H "Authorization: Bearer '
        + power_user_token
        + '" http://localhost:7777/agents'
    )
    print(
        'curl -X POST -H "Authorization: Bearer ' + power_user_token + '" \\\n'
        '  -F "message=test" http://localhost:7777/agents/web-search-agent/runs'
    )

    print(
        "\n# Test limited user (should only see 2 agents: web-search-agent and analyst-agent):"
    )
    print(
        'curl -H "Authorization: Bearer '
        + limited_user_token
        + '" http://localhost:7777/agents'
    )
    print(
        'curl -X POST -H "Authorization: Bearer ' + limited_user_token + '" \\\n'
        '  -F "message=test" http://localhost:7777/agents/web-search-agent/runs'
    )

    print("\n# Test read-only user (should see all agents but cannot run):")
    print(
        'curl -H "Authorization: Bearer '
        + readonly_user_token
        + '" http://localhost:7777/agents'
    )
    print(
        'curl -X POST -H "Authorization: Bearer ' + readonly_user_token + '" \\\n'
        '  -F "message=test" http://localhost:7777/agents/web-search-agent/runs  # Should fail'
    )

    print("\n# Test wildcard user (should work for any agent):")
    print(
        'curl -H "Authorization: Bearer '
        + wildcard_user_token
        + '" http://localhost:7777/agents'
    )
    print(
        'curl -X POST -H "Authorization: Bearer ' + wildcard_user_token + '" \\\n'
        '  -F "message=test" http://localhost:7777/agents/admin-agent/runs'
    )

    print("\n" + "=" * 80)
    print("SCOPE CHECKING BEHAVIOR")
    print("=" * 80)
    print("""
For GET /agents:
- Filters the agent list based on user's scopes
- 'agents:web-search-agent:read' -> only see web-search-agent
- 'agents:*:read' -> see all agents (wildcard)
- 'agents:read' -> see all agents (global scope)

For POST /agents/{agent_id}/runs:
- Checks for matching scopes with resource ID
- Requires either:
  * 'agents:<agent_id>:run' (specific agent)
  * 'agents:*:run' (any agent - wildcard)
  * 'agents:run' (global scope)
  * 'agent_os:admin' (full access)

AUDIENCE VERIFICATION:
- Invalid audience returns 401 Unauthorized
    """)

    print("\n" + "=" * 80 + "\n")

    # Serve the application
    agent_os.serve(app="advanced_scopes:app", port=7777, reload=True)
