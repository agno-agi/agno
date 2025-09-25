"""
This example demonstrates how to use our JWT middleware with AgentOS.
The middleware will automatically inject user_id and session_id into endpoint parameters
when they are present in the JWT token and the endpoint accepts them.
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.tools.duckduckgo import DuckDuckGoTools

# JWT Secret (use environment variable in production)
JWT_SECRET = "a-string-secret-at-least-256-bits-long"

# Setup database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


# Define a tool that uses dependencies claims
def get_user_details(dependencies: dict):
    """
    Get the current user's details.
    """
    return {
        "name": dependencies.get("name"),
        "email": dependencies.get("email"),
        "roles": dependencies.get("roles"),
    }


# Create agent
research_agent = Agent(
    id="user-agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[get_user_details],
    instructions="You are a user agent that can get user details if the user asks for them.",
)


agent_os = AgentOS(
    description="JWT Protected AgentOS",
    agents=[research_agent],
)

# Get the final app
app = agent_os.get_app()

# Add JWT middleware to the app
# This middleware will automatically inject JWT values into endpoint parameters
app.add_middleware(
    JWTMiddleware,
    secret_key=JWT_SECRET,
    algorithm="HS256",
    token_prefix="Bearer",
    user_id_claim="sub",  # Extract user_id from 'sub' claim
    session_id_claim="session_id",  # Extract session_id from 'session_id' claim
    dependencies_claims=["name", "email", "roles"],
    validate=False,  # We only want parameter injection, not token validation
)

if __name__ == "__main__":
    """
    Run your AgentOS with JWT parameter injection.
    
    The middleware will automatically inject user_id and session_id from the JWT token
    into endpoint parameters when:
    1. The endpoint accepts these parameters (e.g., /agents/{agent_id}/runs)
    2. The JWT contains the corresponding claims
    3. The parameters are not already provided in the request
    
    Test by calling /agents/user-agent/runs with a message: "What do you know about me?"
    """
    # Test token with user_id and session_id:
    payload = {
        "sub": "user_123",  # This will be injected as user_id parameter
        "session_id": "demo_session_456",  # This will be injected as session_id parameter
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
        # Dependency claims
        "name": "John Doe",
        "email": "john.doe@example.com",
        "roles": ["admin", "user"],
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    print("Test token:")
    print(token)
    agent_os.serve(app="agent_os_with_jwt_middleware:app", port=7777, reload=True)
