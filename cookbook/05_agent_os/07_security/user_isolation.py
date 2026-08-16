"""
JWT RBAC with per-user data isolation
=====================================

Turn on AuthorizationConfig(user_isolation=True) so non-admin session reads
and writes are pinned to the JWT subject. The smoke creates two sessions,
proves each user sees only their own row, and proves admin bypass.

Prerequisites: none
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/user_isolation.py
Try: inspect the session ids printed by the local isolation smoke
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create an isolated AgentOS
# ---------------------------------------------------------------------------

OS_ID = "isolation-security-demo"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY", "development-secret-at-least-256-bits-long"
)

db = SqliteDb(db_file="tmp/security_user_isolation.db")
isolation_agent = Agent(
    id="isolation-agent",
    name="Isolation Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)
agent_os = AgentOS(
    id=OS_ID,
    agents=[isolation_agent],
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
        user_isolation=True,
    ),
)
app = agent_os.get_app()


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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def run_smoke() -> dict[str, object]:
    suffix = uuid4().hex[:8]
    alice_session = f"alice-{suffix}"
    bob_session = f"bob-{suffix}"
    alice_user = f"alice-{suffix}"
    bob_user = f"bob-{suffix}"
    user_scopes = ["sessions:read", "sessions:write"]
    alice = make_token(alice_user, user_scopes)
    bob = make_token(bob_user, user_scopes)
    admin = make_token("security-admin", ["agent_os:admin"])

    with TestClient(app) as client:
        alice_create = client.post(
            "/sessions?type=agent",
            json={
                "session_id": alice_session,
                "agent_id": "isolation-agent",
                "user_id": "spoofed-owner",
            },
            headers=_auth(alice),
        )
        bob_create = client.post(
            "/sessions?type=agent",
            json={
                "session_id": bob_session,
                "agent_id": "isolation-agent",
            },
            headers=_auth(bob),
        )
        alice_rows = client.get("/sessions?type=agent", headers=_auth(alice)).json()[
            "data"
        ]
        bob_rows = client.get("/sessions?type=agent", headers=_auth(bob)).json()["data"]
        admin_rows = client.get("/sessions?type=agent", headers=_auth(admin)).json()[
            "data"
        ]

    assert alice_create.status_code == 201, alice_create.text
    assert bob_create.status_code == 201, bob_create.text
    assert alice_create.json()["user_id"] == alice_user
    assert {row["session_id"] for row in alice_rows} == {alice_session}
    assert {row["session_id"] for row in bob_rows} == {bob_session}
    assert {alice_session, bob_session}.issubset(
        {row["session_id"] for row in admin_rows}
    )
    return {
        "alice_session": alice_session,
        "bob_session": bob_session,
        "alice_visible": len(alice_rows),
        "bob_visible": len(bob_rows),
        "admin_visible": len(admin_rows),
    }


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    isolation_result = run_smoke()
    print("Per-user isolation smoke passed:")
    print(isolation_result)
    agent_os.serve(app=app, port=7777)
