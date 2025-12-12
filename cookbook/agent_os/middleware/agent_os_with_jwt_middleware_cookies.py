"""
This example demonstrates how to use JWT middleware with cookies instead of Authorization headers.
This is useful for web applications that prefer to store JWT tokens in HTTP-only cookies for security.
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware, TokenSource
from fastapi import FastAPI, Response

# JWT Secret (use environment variable in production)
JWT_SECRET = "a-string-secret-at-least-256-bits-long"

# Setup database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")


def get_user_profile(dependencies: dict) -> dict:
    """
    Get the current user's profile.
    """
    return {
        "name": dependencies.get("name", "Unknown"),
        "email": dependencies.get("email", "Unknown"),
        "roles": dependencies.get("roles", []),
        "organization": dependencies.get("org", "Unknown"),
    }


# Create agent
profile_agent = Agent(
    id="profile-agent",
    name="Profile Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[get_user_profile],
    instructions="You are a profile agent. You can search for information and access user profiles.",
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
    # Create a test JWT token
    payload = {
        "sub": "cookie_user_789",
        "session_id": "cookie_session_123",
        "name": "Jane Smith",
        "email": "jane.smith@example.com",
        "roles": ["user", "premium"],
        "org": "Example Corp",
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
    excluded_route_paths=[
        "/set-auth-cookie",
        "/clear-auth-cookie",
    ],
    token_source=TokenSource.COOKIE,  # Extract JWT from cookies
    cookie_name="auth_token",  # Name of the cookie containing the JWT
    user_id_claim="sub",  # Extract user_id from 'sub' claim
    session_id_claim="session_id",  # Extract session_id from 'session_id' claim
    dependencies_claims=["name", "email", "roles", "org"],
)


agent_os = AgentOS(
    description="JWT Cookie-Based AgentOS",
    agents=[profile_agent],
    base_app=app,
)

# Get the final app
app = agent_os.get_app()


if __name__ == "__main__":
    """
    Run your AgentOS with JWT cookie authentication.

    This example demonstrates:
    1. JWT tokens stored in HTTP-only cookies (more secure than localStorage)
    2. Automatic JWT claims extraction from cookies
    3. Agent tools that can access user profile information
    4. Cookie management endpoints (set/clear)

    To test:
    1. Start the server
    2. Visit /set-auth-cookie to set the authentication cookie
    3. POST to /agents/profile-agent/runs with message: "What's my user profile?"
    4. The agent will access your profile from the JWT cookie claims
    5. Visit /clear-auth-cookie to logout
    """

    agent_os.serve(
        app="agent_os_with_jwt_middleware_cookies:app", port=7777, reload=True
    )
