"""
Advanced RBAC Example with AgentOS - ALL Scopes Namespaced

This example demonstrates the AgentOS RBAC system where ALL scopes use agent-os namespace:

Scope Format (ALL use agent-os namespace):
1. Global resource scopes: agent-os:<os-id>:resource:action
2. Per-resource scopes: agent-os:<os-id>:resource:<resource-id>:action
3. Wildcard support: agent-os:*:... or agent-os:<os-id>:agents:*:run

Scope Examples:
- agent-os:my-os:system:read - Read system config
- agent-os:my-os:agents:read - List all agents in this OS
- agent-os:my-os:agents:web-agent:read - Read specific agent
- agent-os:my-os:agents:web-agent:run - Run specific agent
- agent-os:*:agents:read - Read agents from ANY OS (wildcard)
- agent-os:my-os:agents:*:run - Run ANY agent in this OS (wildcard)
- admin - Full access to everything

Prerequisites:
- Set JWT_VERIFICATION_KEY environment variable
- Endpoints automatically filter based on user scopes
"""

from datetime import UTC, datetime, timedelta
import os

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
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


# Create AgentOS with specific ID for namespacing
agent_os = AgentOS(
    id="my-production-os",
    name="Production AgentOS",
    description="RBAC Protected AgentOS with Namespaced Scopes",
    agents=[web_search_agent, analyst_agent, admin_agent],
    authorization=True,  # Enable RBAC
)

# Get the app
app = agent_os.get_app()


def create_token(user_id: str, scopes: list[str], hours: int = 24) -> str:
    """Helper function to create JWT tokens with scopes."""
    payload = {
        "sub": user_id,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=hours),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


if __name__ == "__main__":
    """
    Scope Hierarchy and Examples (ALL use agent-os namespace):
    
    1. ADMIN SCOPE (highest privilege):
       - "admin" grants full access to all endpoints
    
    2. GLOBAL RESOURCE SCOPES (OS-wide permissions):
       - "agent-os:my-production-os:system:read" - Read system configuration
       - "agent-os:my-production-os:agents:read" - List all agents in this OS
       - "agent-os:*:agents:read" - List agents from ANY AgentOS instance (wildcard OS)
    
    3. PER-RESOURCE SCOPES (granular permissions - still use agent-os namespace):
       - "agent-os:my-production-os:agents:web-search-agent:read" - Read specific agent
       - "agent-os:my-production-os:agents:web-search-agent:run" - Run specific agent
       - "agent-os:my-production-os:agents:*:run" - Run ANY agent in this OS (wildcard resource)
       - "agent-os:*:agents:*:run" - Run ANY agent in ANY OS (double wildcard)
    """

    # EXAMPLE 1: Admin user - full access
    admin_token = create_token(
        user_id="admin_user",
        scopes=["admin"],
    )

    # EXAMPLE 2: Power user - can list and run all agents in this OS
    power_user_token = create_token(
        user_id="power_user",
        scopes=[
            "agent-os:my-production-os:system:read",
            "agent-os:my-production-os:agents:read",
            "agent-os:my-production-os:agents:run",
            "agent-os:my-production-os:sessions:read",
            "agent-os:my-production-os:sessions:write",
        ],
    )

    # EXAMPLE 3: Limited user - can only run specific agents
    limited_user_token = create_token(
        user_id="limited_user",
        scopes=[
            "agent-os:my-production-os:agents:web-search-agent:read",
            "agent-os:my-production-os:agents:web-search-agent:run",
            "agent-os:my-production-os:agents:analyst-agent:read",
            "agent-os:my-production-os:agents:analyst-agent:run",
            # Note: This user won't see admin-agent in GET /agents
        ],
    )

    # EXAMPLE 4: Read-only user - can only view agents
    readonly_user_token = create_token(
        user_id="readonly_user",
        scopes=[
            "agent-os:my-production-os:agents:*:read",  # Can read all agents in this OS
            "agent-os:my-production-os:system:read",  # Can read system info
            # Cannot run any agents
        ],
    )

    # EXAMPLE 5: Wildcard user - can run any agent across all OS instances
    wildcard_user_token = create_token(
        user_id="wildcard_user",
        scopes=[
            "agent-os:*:agents:read",  # Read agents from any OS
            "agent-os:*:agents:*:run",  # Run any agent in any OS
        ],
    )

    # EXAMPLE 6: Multi-OS user - access to multiple OS instances
    multi_os_user_token = create_token(
        user_id="multi_os_user",
        scopes=[
            "agent-os:my-production-os:agents:read",
            "agent-os:my-production-os:agents:run",
            "agent-os:staging-os:agents:read",
            "agent-os:staging-os:agents:run",
        ],
    )

    print("\n" + "=" * 80)
    print("ADVANCED RBAC TEST TOKENS")
    print("=" * 80)

    print("\n1. ADMIN USER (full access):")
    print("   Scopes: ['admin']")
    print(f"   Token: {admin_token[:50]}...")

    print("\n2. POWER USER (OS-wide access):")
    print("   Scopes: ['agent-os:my-production-os:system:read', ...]")
    print(f"   Token: {power_user_token[:50]}...")

    print("\n3. LIMITED USER (specific agents only):")
    print("   Scopes: ['agent-os:my-production-os:agents:web-search-agent:read', ...]")
    print(f"   Token: {limited_user_token[:50]}...")

    print("\n4. READ-ONLY USER (view only):")
    print(
        "   Scopes: ['agent-os:my-production-os:agents:*:read', 'agent-os:my-production-os:system:read']"
    )
    print(f"   Token: {readonly_user_token[:50]}...")

    print("\n5. WILDCARD USER (any agent, any OS):")
    print("   Scopes: ['agent-os:*:agents:read', 'agent-os:*:agents:*:run']")
    print(f"   Token: {wildcard_user_token[:50]}...")

    print("\n" + "=" * 80)
    print("TEST COMMANDS")
    print("=" * 80)

    print("\n# Test admin access (should work for all endpoints):")
    print(f'curl -H "Authorization: Bearer {admin_token}" http://localhost:7777/agents')
    print(f'curl -H "Authorization: Bearer {admin_token}" http://localhost:7777/config')

    print("\n# Test power user (should see all agents and run any):")
    print(
        f'curl -H "Authorization: Bearer {power_user_token}" http://localhost:7777/agents'
    )
    print(
        f'curl -X POST -H "Authorization: Bearer {power_user_token}" \\\n'
        f'  -F "message=test" http://localhost:7777/agents/web-search-agent/runs'
    )

    print(
        "\n# Test limited user (should only see 2 agents: web-search-agent and analyst-agent):"
    )
    print(
        f'curl -H "Authorization: Bearer {limited_user_token}" http://localhost:7777/agents'
    )
    print(
        f'curl -X POST -H "Authorization: Bearer {limited_user_token}" \\\n'
        f'  -F "message=test" http://localhost:7777/agents/web-search-agent/runs'
    )

    print("\n# Test read-only user (should see all agents but cannot run):")
    print(
        f'curl -H "Authorization: Bearer {readonly_user_token}" http://localhost:7777/agents'
    )
    print(
        f'curl -X POST -H "Authorization: Bearer {readonly_user_token}" \\\n'
        f'  -F "message=test" http://localhost:7777/agents/web-search-agent/runs  # Should fail'
    )

    print("\n# Test wildcard user (should work across any OS and any agent):")
    print(
        f'curl -H "Authorization: Bearer {wildcard_user_token}" http://localhost:7777/agents'
    )
    print(
        f'curl -X POST -H "Authorization: Bearer {wildcard_user_token}" \\\n'
        f'  -F "message=test" http://localhost:7777/agents/admin-agent/runs'
    )

    print("\n" + "=" * 80)
    print("SCOPE CHECKING BEHAVIOR")
    print("=" * 80)
    print("""
For GET /agents:
- Filters the agent list based on user's scopes
- 'agent-os:my-production-os:agents:web-search-agent:read' → only see web-search-agent
- 'agent-os:my-production-os:agents:*:read' → see all agents in this OS
- 'agent-os:my-production-os:agents:read' → see all agents in this OS (global scope)
- 'agent-os:*:agents:read' → see all agents in ANY OS

For POST /agents/{agent_id}/runs:
- Checks for matching scopes with resource ID
- Requires either:
  * 'agent-os:my-production-os:agents:<agent_id>:run' (specific agent)
  * 'agent-os:my-production-os:agents:*:run' (any agent in this OS - wildcard)
  * 'agent-os:*:agents:*:run' (any agent in any OS - double wildcard)
  * 'admin' (full access)

All scopes MUST use the agent-os namespace format!
    """)

    print("\n" + "=" * 80 + "\n")

    # Serve the application
    agent_os.serve(app="advanced_scopes:app", port=7777, reload=True)
