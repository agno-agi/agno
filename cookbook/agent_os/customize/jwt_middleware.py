"""
This example demonstrates how to use our JWT middleware with AgentOS
"""

import jwt
from datetime import datetime, timedelta, UTC
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

# Create agent
research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    markdown=True,
)


agent_os = AgentOS(
    description="JWT Protected AgentOS",
    agents=[research_agent],
    middleware=[
        (
            JWTMiddleware,
            {
                "secret_key": JWT_SECRET,
                "algorithm": "HS256",
                "token_prefix": "Bearer",
                "user_id_claim": "user_id",
                "validate_token": False,
            },
        ),
    ],
)

# Get the final app
app = agent_os.get_app()

if __name__ == "__main__":
    """
    Run your AgentOS with JWT user_id extraction.
    """
    # Test token:
    payload = {
            "sub": "user_123",
            "username": "demo",
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    print("Test token:")
    print(token)
    agent_os.serve(app="jwt_middleware:app", port=7777, reload=True)
