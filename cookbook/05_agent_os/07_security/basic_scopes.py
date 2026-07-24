"""
JWT scopes and audience verification
====================================

Protect AgentOS with an HS256 JWT, the default scope map, and an audience
bound to this AgentOS instance. The in-file smoke proves 200, 401, and 403
outcomes without calling a model.

Prerequisites: none for the smoke; OPENAI_API_KEY for live agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/basic_scopes.py
Try: use the printed reader, runner, and admin tokens against port 7777
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create JWT-protected AgentOS
# ---------------------------------------------------------------------------

OS_ID = "security-demo"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY", "development-secret-at-least-256-bits-long"
)

security_agent = Agent(
    id="security-agent",
    name="Security Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer questions about the secured AgentOS.",
)

agent_os = AgentOS(
    id=OS_ID,
    agents=[security_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
    ),
)
app = agent_os.get_app()


def make_token(subject: str, scopes: list[str], *, audience: str = OS_ID) -> str:
    """Mint a short-lived development token for this lesson."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "aud": audience,
            "scopes": scopes,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def run_smoke() -> dict[str, int]:
    """Exercise authentication, authorization, and audience rejection."""
    reader = make_token("reader", ["agents:read"])
    runner = make_token("runner", ["agents:read", "agents:run"])
    admin = make_token("admin", ["agent_os:admin"])
    wrong_audience = make_token(
        "other-service-user", ["agents:read"], audience="another-agent-os"
    )

    with TestClient(app) as client:
        statuses = {
            "reader_list": client.get(
                "/agents", headers={"Authorization": f"Bearer {reader}"}
            ).status_code,
            "reader_run": client.post(
                "/agents/security-agent/runs",
                data={"message": "hello", "stream": "false"},
                headers={"Authorization": f"Bearer {reader}"},
            ).status_code,
            "runner_list": client.get(
                "/agents", headers={"Authorization": f"Bearer {runner}"}
            ).status_code,
            "admin_config": client.get(
                "/config", headers={"Authorization": f"Bearer {admin}"}
            ).status_code,
            "wrong_audience": client.get(
                "/agents",
                headers={"Authorization": f"Bearer {wrong_audience}"},
            ).status_code,
        }

    expected = {
        "reader_list": 200,
        "reader_run": 403,
        "runner_list": 200,
        "admin_config": 200,
        "wrong_audience": 401,
    }
    assert statuses == expected, statuses
    return statuses


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    smoke_statuses = run_smoke()
    print("Local JWT/RBAC smoke passed:")
    for check_name, status_code in smoke_statuses.items():
        print(f"  {check_name}: {status_code}")

    print("\nReader token (agents:read):")
    print(make_token("reader", ["agents:read"]))
    print("\nRunner token (agents:read, agents:run):")
    print(make_token("runner", ["agents:read", "agents:run"]))
    print("\nAdmin token (agent_os:admin):")
    print(make_token("admin", ["agent_os:admin"]))
    agent_os.serve(app=app, port=7777)
