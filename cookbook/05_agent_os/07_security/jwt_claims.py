"""
JWT claims into request state and agent dependencies
====================================================

Extract trusted claims into request.state, session state, and the dependencies
carried by the RunContext passed to agent tools. A local /whoami route calls
the same tool function to make the plumbing visible without a model request.

Prerequisites: none for the smoke; OPENAI_API_KEY for live agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/jwt_claims.py
Try: call GET /whoami with the printed token
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.run import RunContext
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create claims-aware AgentOS
# ---------------------------------------------------------------------------

OS_ID = "claims-security-demo"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY", "development-secret-at-least-256-bits-long"
)


def get_user_details(run_context: RunContext) -> dict[str, Any]:
    """Return the trusted profile claims injected into the run context."""
    dependencies = run_context.dependencies or {}
    return {
        "name": dependencies.get("name"),
        "email": dependencies.get("email"),
        "roles": dependencies.get("roles", []),
    }


base_app = FastAPI()


@base_app.get("/whoami")
async def whoami(request: Request) -> dict[str, Any]:
    """Show the exact trusted values made available downstream."""
    run_context = RunContext(
        run_id="whoami",
        session_id="whoami",
        user_id=request.state.user_id,
        dependencies=request.state.dependencies,
        session_state=request.state.session_state,
    )
    return {
        "user_id": request.state.user_id,
        "audience": request.state.audience,
        "dependencies": get_user_details(run_context),
        "session_state": request.state.session_state,
    }


base_app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    verify_audience=True,
    dependencies_claims=["name", "email", "roles"],
    session_state_claims=["organization_id"],
)

profile_agent = Agent(
    id="profile-agent",
    name="Profile Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[get_user_details],
    instructions="Use get_user_details when asked about the authenticated user.",
)
agent_os = AgentOS(
    id=OS_ID,
    agents=[profile_agent],
    base_app=base_app,
)
app = agent_os.get_app()


def make_token() -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "user-123",
            "aud": OS_ID,
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "roles": ["developer", "reviewer"],
            "organization_id": "org-456",
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def run_smoke() -> dict[str, Any]:
    token = make_token()
    with TestClient(app) as client:
        response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {
        "user_id": "user-123",
        "audience": OS_ID,
        "dependencies": {
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "roles": ["developer", "reviewer"],
        },
        "session_state": {"organization_id": "org-456"},
    }, payload
    return payload


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    observed_claims = run_smoke()
    print("Trusted request state:")
    print(observed_claims)
    print("\nJWT:")
    print(make_token())
    agent_os.serve(app=app, port=7777)
