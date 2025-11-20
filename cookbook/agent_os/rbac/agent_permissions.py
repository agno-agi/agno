"""
Basic RBAC Example with AgentOS

This example demonstrates how to enable RBAC (Role-Based Access Control)
with JWT token authentication in AgentOS using middleware.

Prerequisites:
- Set JWT_SECRET_KEY environment variable or pass it to middleware
- Endpoints are automatically protected with default scope mappings
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.mcp import MCPTools

# JWT Secret (use environment variable in production)
JWT_SECRET = "your-secret-key-at-least-256-bits-long"

# Setup database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

web_search_agent = Agent(
    id="web-search-agent",
    name="Web Search Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    markdown=True,
)

agno_agent = Agent(
    id="agno-agent",
    name="Agno Agent",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")],
    db=db,
    add_history_to_context=True,
    markdown=True,
)


# Create AgentOS
agent_os = AgentOS(
    description="RBAC Protected AgentOS",
    agents=[web_search_agent, agno_agent],
)

# Get the app and add RBAC middleware
app = agent_os.get_app()

# Add JWT middleware with RBAC enabled using custom scope mappings
app.add_middleware(
    JWTMiddleware,
    secret_key=JWT_SECRET,
    algorithm="HS256",
    scope_mappings={
        # Define the scopes for the agents
        # Other scopes will remain the same
        "POST /agents/web-search-agent/runs": ["agents:web-search-agent"],
        "POST /agents/agno-agent/runs": ["agents:agno-agent"],
        "POST /agents/*/runs": [],
    },
    admin_scope="admin",  # Admin can bypass all checks
)

if __name__ == "__main__":
    """
    Run your AgentOS with RBAC enabled.
    
    Default scope mappings protect all endpoints:
    - GET /agents/{agent_id}: requires "agents:read"
    - POST /agents/{agent_id}/runs: requires "agents:run"
    - GET /sessions: requires "sessions:read"
    - GET /memory: requires "memory:read"
    - etc.
    
    Special scopes:
    - "admin": grants access to all endpoints
    - "agents:*": grants all agent permissions
    
    Test with a JWT token that includes scopes:
    """
    # Create test tokens with different scopes
    web_search_user_token_payload = {
        "sub": "user_123",
        "scopes": ["agents:web-search-agent"],
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    web_search_user_token = jwt.encode(
        web_search_user_token_payload, JWT_SECRET, algorithm="HS256"
    )

    agno_user_token_payload = {
        "sub": "user_456",
        "scopes": ["agents:agno-agent"],
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    agno_user_token = jwt.encode(agno_user_token_payload, JWT_SECRET, algorithm="HS256")

    print("\n" + "=" * 60)
    print("RBAC Test Tokens")
    print("=" * 60)
    print("\nWeb Search User Token (agents:web-search-agent):")
    print(web_search_user_token)
    print("\nAgno User Token (agents:agno-agent):")
    print(agno_user_token)
    print("\n" + "=" * 60)
    print("\nTest commands:")
    print(
        f'\ncurl -H "Authorization: Bearer {web_search_user_token}" http://localhost:7777/agents/web-search-agent/runs'
    )
    print(
        f'\ncurl -H "Authorization: Bearer {agno_user_token}" http://localhost:7777/agents/agno-agent/runs'
    )
    print("\n" + "=" * 60 + "\n")

    agent_os.serve(app="agent_permissions:app", port=7777, reload=True)
