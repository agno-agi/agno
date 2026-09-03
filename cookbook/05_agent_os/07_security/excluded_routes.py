"""
Excluding routes from JWT authentication
========================================

Use AuthorizationConfig.excluded_route_paths to mark custom routes as public
(no JWT required) while keeping the rest of your AgentOS protected.

This is useful for:
- Public API endpoints (webhooks, health checks for external services)
- Login/signup flows that don't have a token yet
- Static assets or documentation pages

Patterns use fnmatch syntax:
- "/public" - exact match
- "/api/public/*" - matches /api/public/anything (including nested paths)
- "/v?/health" - matches /v1/health, /v2/health, etc.

Default exclusions (/, /health, /info, /docs, /redoc, /openapi.json) are
always included - your custom paths are additive, not a replacement.

Prerequisites: none for the smoke
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/excluded_routes.py
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OS_ID = "excluded-routes-demo"
JWT_SECRET = "demo-secret-key-must-be-at-least-256-bits-long"

# ---------------------------------------------------------------------------
# Build app with public and protected routes
# ---------------------------------------------------------------------------

base_app = FastAPI(title="Excluded Routes Demo")


@base_app.get("/public/status")
async def public_status():
    """Public endpoint - no auth required."""
    return {"status": "ok", "auth": "not required"}


@base_app.get("/webhooks/stripe")
async def stripe_webhook():
    """Webhook endpoint - auth handled by Stripe signature verification."""
    return {"received": True}


@base_app.get("/webhooks/github")
async def github_webhook():
    """Another webhook - also excluded from JWT auth."""
    return {"received": True}


@base_app.get("/api/private/data")
async def private_data():
    """Private endpoint - requires valid JWT."""
    return {"data": "secret", "auth": "required"}


# ---------------------------------------------------------------------------
# Create AgentOS with excluded routes
# ---------------------------------------------------------------------------

agent = Agent(
    id="demo-agent",
    name="Demo Agent",
    model=OpenAIResponses(id="gpt-5.5"),
)

agent_os = AgentOS(
    id=OS_ID,
    agents=[agent],
    base_app=base_app,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        excluded_route_paths=[
            "/public/*",
            "/webhooks/*",
        ],
    ),
)

app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Helper to create tokens
# ---------------------------------------------------------------------------


def create_token(sub: str = "demo-user") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": sub,
            "scopes": ["agents:read", "agents:run"],
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


def run_smoke() -> dict[str, int]:
    client = TestClient(app)
    token = create_token()

    results = {
        # Custom exclusions - should work without auth
        "public_status": client.get("/public/status").status_code,
        "webhook_stripe": client.get("/webhooks/stripe").status_code,
        "webhook_github": client.get("/webhooks/github").status_code,
        # Default exclusions - should still work
        "health": client.get("/health").status_code,
        "info": client.get("/info").status_code,
        # Protected routes - should fail without auth
        "private_no_auth": client.get("/api/private/data").status_code,
        "agents_no_auth": client.get("/agents").status_code,
        # Protected routes - should work with auth
        "private_with_auth": client.get(
            "/api/private/data",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code,
        "agents_with_auth": client.get(
            "/agents",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code,
    }

    # Validate
    expected = {
        "public_status": 200,
        "webhook_stripe": 200,
        "webhook_github": 200,
        "health": 200,
        "info": 200,
        "private_no_auth": 401,
        "agents_no_auth": 401,
        "private_with_auth": 200,
        "agents_with_auth": 200,
    }
    assert results == expected, f"Mismatch: {results}"
    return results


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = run_smoke()
    print("Excluded routes smoke test:")
    print("-" * 40)
    for name, status in results.items():
        icon = "public" if status == 200 and "no_auth" not in name else ("OK" if status == 200 else "blocked")
        print(f"  {name}: {status} ({icon})")
    print("-" * 40)
    print("Smoke passed. Starting server on port 7778...")
    agent_os.serve(app=app, port=7778)
