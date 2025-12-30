"""
This example demonstrates how to use our JWT middleware with your custom FastAPI app.

# Note: This example won't work with the AgentOS UI, because of the token validation mechanism in the JWT middleware.
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.tools.duckduckgo import DuckDuckGoTools
from fastapi import FastAPI, Form, HTTPException

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

# Create custom FastAPI app
app = FastAPI(
    title="Example Custom App",
    version="1.0.0",
)

# Add JWT middleware
app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",  # Use HS256 for symmetric key
    excluded_route_paths=[
        "/auth/login"
    ],  # We don't want to validate the token for the login endpoint
)


# Custom routes that shouldn't be protected by JWT
@app.post("/auth/login")
async def login(username: str = Form(...), password: str = Form(...)):
    """Login endpoint that returns JWT token"""
    if username == "demo" and password == "password":
        payload = {
            "sub": "user_123",
            "username": username,
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        return {"access_token": token, "token_type": "bearer"}

    raise HTTPException(status_code=401, detail="Invalid credentials")


# Clean AgentOS setup with tuple middleware pattern! ✨
agent_os = AgentOS(
    description="JWT Protected AgentOS",
    agents=[research_agent],
    base_app=app,
)

# Get the final app
app = agent_os.get_app()

if __name__ == "__main__":
    """
    Run your AgentOS with JWT middleware applied to the entire app.

    Test endpoints:
    1. POST /auth/login - Login to get JWT token
    2. GET /config - Protected route (requires JWT)
    """
    agent_os.serve(
        app="custom_fastapi_app_with_jwt_middleware:app", port=7777, reload=True
    )
