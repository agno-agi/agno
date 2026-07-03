"""
Roles protecting real data - who can delete a chat session

(If roles are new to you, read managed_roles.py first.)

A "session" is one saved conversation with an agent. Deleting one throws away real
data, so not everyone should be allowed to. This file shows roles protecting an
actual operation, not a toy one.

Three jobs:
- support  -> can LOOK at sessions, nothing else
- operator -> can look, edit, and DELETE sessions
- admin    -> can do anything

We put two saved sessions in the database, then watch what each person is allowed
to do. The key moment: the support person tries to delete a session and gets
BLOCKED, while the operator deletes one for real and the count drops from 2 to 1.
That is the whole idea of authorization in one screen: the right people get
through, the wrong ones get stopped, before any data is touched.

Run it:
    pip install "agno[roles]"
    python managed_roles_sessions.py
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
roles.set_role_scopes(
    "operator", ["sessions:read", "sessions:write", "sessions:delete"]
)
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
db.upsert_session(
    AgentSession(
        session_id="sess-123",
        agent_id="research-agent",
        user_id="customer-a",
        created_at=_now,
    )
)
db.upsert_session(
    AgentSession(
        session_id="sess-456",
        agent_id="research-agent",
        user_id="customer-b",
        created_at=_now,
    )
)

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
            {
                "sub": sub,
                "aud": OS_ID,
                "scopes": [],
                "exp": datetime.now(UTC) + timedelta(hours=24),
            },
            JWT_SECRET,
            algorithm="HS256",
        )

    def auth(sub: str) -> dict:
        return {"Authorization": f"Bearer {token(sub)}"}

    def show(label: str, r, note: str = "") -> None:
        # 200/204 means it went through; 401/403 means it was bounced.
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:44s} -> {verdict:7s} ({r.status_code})  {note}")

    def count(sub: str) -> int:
        r = client.get("/sessions?type=agent", headers=auth(sub))
        return r.json()["meta"]["total_count"] if r.status_code == 200 else -1

    print("\n" + "=" * 78)
    print("WHO CAN TOUCH THE SAVED SESSIONS")
    print("=" * 78)
    print("  bob = support (look only) | val = operator (look, edit, delete)")
    print(f"  saved sessions right now: {count('val')}\n")

    show(
        "bob (support)  tries to LOOK at sessions",
        client.get("/sessions?type=agent", headers=auth("bob")),
        "support can look",
    )
    show(
        "bob (support)  tries to RENAME a session",
        client.patch("/sessions/sess-123", headers=auth("bob"), json={"name": "x"}),
        "editing isn't allowed -> bounced",
    )
    show(
        "bob (support)  tries to DELETE a session",
        client.delete("/sessions/sess-123", headers=auth("bob")),
        "deleting isn't allowed -> bounced",
    )
    show(
        "val (operator) tries to DELETE a session",
        client.delete("/sessions/sess-123", headers=auth("val")),
        "operators can delete -> done for real",
    )

    print(
        f"\n  saved sessions now: {count('val')}  (was 2 - the operator's delete really happened)"
    )
    print("=" * 78)
    print("the point: the support person was stopped before any data was touched.")
    print("only the operator's delete went through, and you can see the count drop.")
    print("=" * 78)
