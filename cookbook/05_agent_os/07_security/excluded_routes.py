"""
Excluding routes from JWT authentication
========================================

Use AuthorizationConfig.excluded_route_paths to mark custom routes as public.
Patterns use fnmatch syntax: "/public/*" matches /public/anything.

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
# Build app with a public route
# ---------------------------------------------------------------------------

OS_ID = "excluded-routes-demo"
JWT_SECRET = "demo-secret-key-must-be-at-least-256-bits-long"

base_app = FastAPI()


@base_app.get("/public/status")
async def public_status():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Create AgentOS with excluded routes
# ---------------------------------------------------------------------------

agent = Agent(
    id="demo-agent",
    name="Demo Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

agent_os = AgentOS(
    id=OS_ID,
    agents=[agent],
    base_app=base_app,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        excluded_route_paths=["/public/*"],
    ),
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


def run_smoke():
    with TestClient(app) as client:
        # Public route works without auth
        assert client.get("/public/status").status_code == 200
        # Default exclusion still works
        assert client.get("/health").status_code == 200
        # Protected route requires auth
        assert client.get("/agents").status_code == 401
        # Protected route works with token
        token = jwt.encode(
            {
                "sub": "user",
                "scopes": ["agents:read"],
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            JWT_SECRET,
            algorithm="HS256",
        )
        assert (
            client.get(
                "/agents", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 200
        )


if __name__ == "__main__":
    run_smoke()
    print("Smoke passed.")
    agent_os.serve(app=app, port=7777)
