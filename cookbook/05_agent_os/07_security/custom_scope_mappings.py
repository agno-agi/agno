"""
Custom route-to-scope mappings
==============================

Override selected entries in the default AgentOS scope map and add a second
application scope to agent runs. The smoke proves the override on GET /config.

Prerequisites: none for the smoke; OPENAI_API_KEY for live agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/custom_scope_mappings.py
Try: call GET /config with an app:read token
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create AgentOS with custom mappings
# ---------------------------------------------------------------------------

OS_ID = "custom-scope-demo"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY", "development-secret-at-least-256-bits-long"
)

custom_scope_mappings = {
    "GET /config": ["app:read"],
    "POST /agents/*/runs": ["agents:run", "app:execute"],
    "GET /sessions": ["app:admin"],
}

security_agent = Agent(
    id="security-agent",
    name="Security Agent",
    model=OpenAIResponses(id="gpt-5.5"),
)
agent_os = AgentOS(id=OS_ID, agents=[security_agent])
app = agent_os.get_app()
app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    authorization=True,
    verify_audience=True,
    scope_mappings=custom_scope_mappings,
)


def make_token(subject: str, scopes: list[str]) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "aud": OS_ID,
            "scopes": scopes,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def run_smoke() -> dict[str, int]:
    custom_reader = make_token("custom-reader", ["app:read"])
    default_reader = make_token("default-reader", ["agents:read"])
    with TestClient(app) as client:
        statuses = {
            "custom_reader": client.get(
                "/config",
                headers={"Authorization": f"Bearer {custom_reader}"},
            ).status_code,
            "default_reader": client.get(
                "/config", headers={"Authorization": f"Bearer {default_reader}"}
            ).status_code,
        }
    assert statuses == {"custom_reader": 200, "default_reader": 403}, statuses
    return statuses


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    smoke_statuses = run_smoke()
    print(f"app:read GET /config: {smoke_statuses['custom_reader']}")
    print(f"agents:read GET /config after override: {smoke_statuses['default_reader']}")
    print("Agent runs require both agents:run and app:execute.")
    agent_os.serve(app=app, port=7777)
