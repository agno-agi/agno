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
from agno.tools.duckduckgo import DuckDuckGoTools

# JWT Secret (use environment variable in production)
JWT_SECRET = "your-secret-key-at-least-256-bits-long"

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

# Create AgentOS
agent_os = AgentOS(
    description="RBAC Protected AgentOS",
    agents=[research_agent],
    authorization=True,
    authorization_secret=JWT_SECRET,
)

# Get the app and add RBAC middleware
app = agent_os.get_app()


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
    user_token_payload = {
        "sub": "user_123",
        "session_id": "session_456",
        "scopes": ["agents:read", "agents:run"],
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    user_token = jwt.encode(user_token_payload, JWT_SECRET, algorithm="HS256")

    admin_token_payload = {
        "sub": "admin_789",
        "session_id": "admin_session_123",
        "scopes": ["admin"],  # Admin has access to everything
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    admin_token = jwt.encode(admin_token_payload, JWT_SECRET, algorithm="HS256")

    print("\n" + "=" * 60)
    print("RBAC Test Tokens")
    print("=" * 60)
    print("\nUser Token (agents:read, agents:run):")
    print(user_token)
    print("\nAdmin Token (admin - full access):")
    print(admin_token)
    print("\n" + "=" * 60)
    print("\nTest commands:")
    print(
        f'\ncurl -H "Authorization: Bearer {user_token}" http://localhost:7777/agents'
    )
    print(
        f'\ncurl -H "Authorization: Bearer {admin_token}" http://localhost:7777/sessions'
    )
    print("\n" + "=" * 60 + "\n")

    agent_os.serve(app="basic:app", port=7777, reload=True)
