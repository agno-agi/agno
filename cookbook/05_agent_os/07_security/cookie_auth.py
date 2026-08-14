"""
JWT authentication from an HTTP-only cookie
===========================================

Mount login/logout routes on the base FastAPI app, read JWTs from a secure
cookie, and enforce AgentOS scopes normally. The smoke proves both the
unauthenticated 401 and authenticated 200 paths.

Prerequisites: none for the smoke; HTTPS in production
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/cookie_auth.py
Try: GET /auth/cookie, then GET /agents with the returned cookie
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware, TokenSource
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create cookie-authenticated AgentOS
# ---------------------------------------------------------------------------

OS_ID = "cookie-security-demo"
COOKIE_NAME = "agent_os_token"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY", "development-secret-at-least-256-bits-long"
)

base_app = FastAPI()


@base_app.get("/auth/cookie")
async def set_auth_cookie(response: Response) -> dict[str, str]:
    """Stand-in for the successful callback from an identity provider."""
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "cookie-user",
            "aud": OS_ID,
            "scopes": ["agents:read", "agents:run"],
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=3600,
    )
    return {"message": "Authentication cookie set"}


@base_app.delete("/auth/cookie")
async def clear_auth_cookie(response: Response) -> dict[str, str]:
    response.delete_cookie(key=COOKIE_NAME)
    return {"message": "Authentication cookie cleared"}


base_app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    authorization=True,
    token_source=TokenSource.COOKIE,
    cookie_name=COOKIE_NAME,
    verify_audience=True,
    excluded_route_paths=[
        "/",
        "/health",
        "/info",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
        "/auth/cookie",
    ],
)

profile_agent = Agent(
    id="profile-agent",
    name="Profile Agent",
    model=OpenAIResponses(id="gpt-5.5"),
)
agent_os = AgentOS(
    id=OS_ID,
    agents=[profile_agent],
    base_app=base_app,
)
app = agent_os.get_app()


def run_smoke() -> dict[str, int]:
    with TestClient(app, base_url="https://testserver") as client:
        unauthenticated = client.get("/agents").status_code
        cookie_response = client.get("/auth/cookie")
        authenticated = client.get("/agents").status_code

    statuses = {
        "set_cookie": cookie_response.status_code,
        "unauthenticated": unauthenticated,
        "authenticated": authenticated,
    }
    assert COOKIE_NAME in cookie_response.cookies
    assert statuses == {
        "set_cookie": 200,
        "unauthenticated": 401,
        "authenticated": 200,
    }, statuses
    return statuses


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    smoke_statuses = run_smoke()
    for check_name, status_code in smoke_statuses.items():
        print(f"{check_name}: {status_code}")
    print("Production cookies must stay secure, HTTP-only, and CSRF-protected.")
    agent_os.serve(app=app, port=7777)
