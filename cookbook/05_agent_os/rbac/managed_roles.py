"""
Managed Roles Example with AgentOS

This example demonstrates the agno-native managed-roles tier: you define roles
and assignments in agno scope terms and change them at runtime, persisted to your
own DB. There is no Casbin in this file, no model.conf, no Enforcer; the store
hides that engine. A grant or revoke takes effect on the next request with the
SAME token (token-baked scopes can't do this, you'd wait for expiry).

Prerequisites:
- pip install "agno[casbin]"
- Set OPENAI_API_KEY to actually run an agent (authorization is enforced regardless)
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.authz.role_store import ManagedRoleStore
from agno.os.config import AuthorizationConfig

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "managed-roles-os"

os.makedirs("tmp", exist_ok=True)

# Define your roles in agno scope terms. Policy persists to your DB (point the
# url at Postgres in production). This is the entire authorization model.
roles = ManagedRoleStore(db_url="sqlite:///tmp/managed_roles.db")
roles.set_role_scopes("viewer", ["agents:*:read"])
roles.set_role_scopes("member", ["agents:*:read", "agents:research-agent:run"])
roles.set_role_scopes("admin", ["agent_os:admin"])
roles.assign("bob", "viewer")  # bob can read agents but not run them
roles.assign("alice", "admin")

# Setup database
db = SqliteDb(db_file="tmp/agentos.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
)

# Create AgentOS using the managed-role store as the provider. The only wiring.
agent_os = AgentOS(
    id=OS_ID,
    description="Managed-roles AgentOS",
    agents=[research_agent],
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
    Run this file to print managed-role decisions for each caller.

    Roles (defined above, persisted to tmp/managed_roles.db):
    - viewer -> read agents
    - member -> read agents + run research-agent
    - admin  -> everything
    bob is a viewer, alice is an admin. No scopes are baked into the tokens; the
    store decides what each user can do. The scenario below promotes bob to member
    at runtime, shows his run flip to 200, then revokes it, all with the same token.
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

    print("\n" + "=" * 70)
    print("Managed roles — running the scenario for you")
    print("=" * 70)
    show("bob (viewer)  GET  /agents/research-agent", client.get("/agents/research-agent", headers=auth("bob")), "can read")
    show("bob (viewer)  POST /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "viewer -> blocked")
    roles.assign("bob", "member")  # promote at runtime
    show("bob (member)  POST /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "promoted live -> SAME token")
    roles.unassign("bob", "member")  # revoke at runtime
    show("bob (revoked) POST /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "revoked -> blocked again")
    show("alice (admin) POST /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("alice"), data={"message": "hi"}), "admin -> all")
    print("=" * 70)
