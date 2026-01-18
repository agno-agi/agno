"""
Basic RBAC Example with AgentOS

This example demonstrates how to enable RBAC (Role-Based Access Control)
with JWT token authentication in AgentOS using middleware with cookie-based tokens.

Prerequisites:
- Set JWT_VERIFICATION_KEY environment variable or pass it to middleware
- Endpoints are automatically protected with default scope mappings
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware, TokenSource
from agno.tools.duckduckgo import DuckDuckGoTools
from fastapi import FastAPI, Response

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


app = FastAPI()


# Add a simple endpoint to set the JWT authentication cookie
@app.get("/set-auth-cookie")
async def set_auth_cookie(response: Response):
    """
    Endpoint to set the JWT authentication cookie.
    In a real application, this would be done after successful login.
    """
    # Create a test JWT token with aud claim
    payload = {
        "sub": "user_123",
        "session_id": "cookie_session_123",
        "scopes": ["agents:read", "agents:run", "sessions:read", "sessions:write"],
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Set HTTP-only cookie (more secure than localStorage for JWT storage)
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,  # Prevents access from JavaScript (XSS protection)
        secure=True,  # Only send over HTTPS in production
        samesite="strict",  # CSRF protection
        max_age=24 * 60 * 60,  # 24 hours
    )

    return {
        "message": "Authentication cookie set successfully",
        "cookie_name": "auth_token",
        "expires_in": "24 hours",
        "security_features": ["httponly", "secure", "samesite=strict"],
        "instructions": "Now you can make authenticated requests without Authorization headers",
    }


# Add a simple endpoint to clear the JWT authentication cookie
@app.get("/clear-auth-cookie")
async def clear_auth_cookie(response: Response):
    """Endpoint to clear the JWT authentication cookie (logout)."""
    response.delete_cookie(key="auth_token")
    return {"message": "Authentication cookie cleared successfully"}


# Add RBAC middleware configured for cookie-based authentication
app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    authorization=True,
    excluded_route_paths=[
        "/set-auth-cookie",
        "/clear-auth-cookie",
    ],
    token_source=TokenSource.COOKIE,  # Extract JWT from cookies
    cookie_name="auth_token",  # Name of the cookie containing the JWT
    user_id_claim="sub",  # Extract user_id from 'sub' claim
    session_id_claim="session_id",  # Extract session_id from 'session_id' claim
    scopes_claim="scopes",  # Extract scopes from 'scopes' claim
)


# Create AgentOS
agent_os = AgentOS(
    id="my-agent-os",
    description="RBAC Protected AgentOS",
    agents=[research_agent],
    base_app=app,
)

# Get the app and add RBAC middleware
app = agent_os.get_app()


if __name__ == "__main__":
    """
    Run your AgentOS with RBAC enabled.
    
    Audience Verification:
    - Tokens must include `aud` claim matching the AgentOS ID
    - Tokens with wrong audience will be rejected
    
    Default scope mappings protect all endpoints:
    - GET /agents/{agent_id}: requires "agents:read"
    - POST /agents/{agent_id}/runs: requires "agents:run"
    - GET /sessions: requires "sessions:read"
    - GET /memory: requires "memory:read"
    - etc.
    
    Scope format:
    - "agents:read" - List all agents
    - "agents:research-agent:run" - Run specific agent
    - "agents:*:run" - Run any agent
    - "agent_os:admin" - Full access to everything
    
    Test with a JWT token that includes scopes:
    """
    # Create test tokens with different scopes
    # Note: Include `aud` claim with AgentOS ID
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
        "scopes": ["agent_os:admin"],  # Admin has access to everything
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    admin_token = jwt.encode(admin_token_payload, JWT_SECRET, algorithm="HS256")

    print("\n" + "=" * 60)
    print("RBAC Test Tokens")
    print("=" * 60)
    print("\nUser Token (agents:read, agents:run):")
    print(user_token)
    print("\nAdmin Token (agent_os:admin - full access):")
    print(admin_token)
    print("\n" + "=" * 60)
    print("\nTest commands:")
    print(
        '\ncurl -H "Authorization: Bearer '
        + user_token
        + '" http://localhost:7777/agents'
    )
    print(
        '\ncurl -H "Authorization: Bearer '
        + admin_token
        + '" http://localhost:7777/sessions'
    )
    print("\n" + "=" * 60 + "\n")

    agent_os.serve(app="with_cookie:app", port=7777, reload=True)
