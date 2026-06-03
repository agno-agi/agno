"""
Managed Roles Session Access Control Example with AgentOS

This example demonstrates RBAC gating a real AgentOS resource: sessions. Roles
govern the actual session endpoints (GET /sessions, PATCH /sessions/{id},
DELETE /sessions/{id}). A read-only 'support' role can VIEW sessions but is
blocked (403) from editing or deleting them; an 'operator' can delete, and when
it does the session is really gone. There is no Casbin in this file; roles are
defined in agno scope terms and the store hides the engine.

Two sessions are seeded so the blocking is tangible.

Prerequisites:
- pip install "agno[casbin]"
"""

import os
import time
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.authz.role_store import ManagedRoleStore
from agno.os.config import AuthorizationConfig
from agno.session import AgentSession

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "managed-roles-sessions-os"

os.makedirs("tmp", exist_ok=True)

# Define roles in agno scope terms. support is read-only; operator can delete.
roles = ManagedRoleStore(db_url="sqlite:///tmp/managed_roles_sessions.db")
roles.set_role_scopes("support", ["sessions:read"])
roles.set_role_scopes("operator", ["sessions:read", "sessions:write", "sessions:delete"])
roles.set_role_scopes("admin", ["agent_os:admin"])
roles.assign("bob", "support")
roles.assign("val", "operator")
roles.assign("alice", "admin")

# Setup database
db = SqliteDb(db_file="tmp/agentos_sessions.db")

# Demo fixture: seed two sessions directly so the delete is observable without an
# API key. Real apps don't do this; sessions are created by running an agent
# (e.g. agent.print_response("hi", session_id="...")). We seed to stay self-contained.
_now = int(time.time())
db.upsert_session(AgentSession(session_id="sess-123", agent_id="research-agent", user_id="customer-a", created_at=_now))
db.upsert_session(AgentSession(session_id="sess-456", agent_id="research-agent", user_id="customer-b", created_at=_now))

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
)

# Create AgentOS using the managed-role store as the provider.
agent_os = AgentOS(
    id=OS_ID,
    description="Managed-roles AgentOS gating session access",
    agents=[research_agent],
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        authorization_provider=roles.provider,
    ),
)

# Get the app
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run this file to see roles gate the real session endpoints.

    Roles:
    - support  -> sessions:read                 (view only)
    - operator -> sessions:read/write/delete    (full session control)
    - admin    -> everything
    bob is support, val is operator. The scenario below shows support being
    blocked from edit/delete (403) while operator deletes for real (the session
    count drops from 2 to 1).
    """

    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)  # quiet framework logs for a clean transcript
    client = TestClient(app)

    def token(sub: str) -> str:
        return jwt.encode(
            {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=24)},
            JWT_SECRET, algorithm="HS256",
        )

    def auth(sub: str) -> dict:
        return {"Authorization": f"Bearer {token(sub)}"}

    def show(label: str, r, note: str = "") -> None:
        verdict = "DENIED " if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:46s} -> {r.status_code} {verdict}  {note}")

    def count(sub: str) -> int:
        r = client.get("/sessions?type=agent", headers=auth(sub))
        return r.json()["meta"]["total_count"] if r.status_code == 200 else -1

    print("\n" + "=" * 70)
    print("Session access control — running the scenario for you")
    print("=" * 70)
    print(f"  sessions in the DB to start                    : {count('val')}")
    show("bob (support)  GET    /sessions", client.get("/sessions?type=agent", headers=auth("bob")), "can view")
    show("bob (support)  PATCH  /sessions/sess-123", client.patch("/sessions/sess-123", headers=auth("bob"), json={"name": "x"}), "write -> blocked")
    show("bob (support)  DELETE /sessions/sess-123", client.delete("/sessions/sess-123", headers=auth("bob")), "delete -> blocked")
    show("val (operator) DELETE /sessions/sess-123", client.delete("/sessions/sess-123", headers=auth("val")), "really deleted")
    print(f"  sessions in the DB now                         : {count('val')}  <- it's gone")
    print("=" * 70)
