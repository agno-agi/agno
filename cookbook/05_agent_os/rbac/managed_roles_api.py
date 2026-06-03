"""
Managed Roles HTTP Management API Example with AgentOS

This example demonstrates the admin-only REST API for managed roles. Mount one
router and admins can create roles and grant/revoke them with plain HTTP calls,
the change takes effect on the target user's next request (same token). There is
still no Casbin in this file; the store hides that engine.

Every /authz/* route requires an admin caller (satisfies agent_os:admin, by token
scope or by an admin role in the store): non-admins get 403, anonymous 401.

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
from agno.os.authz.audit import DbAuditSink
from agno.os.authz.role_router import get_roles_router
from agno.os.authz.role_store import ManagedRoleStore
from agno.os.config import AuthorizationConfig

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "managed-roles-api-os"

os.makedirs("tmp", exist_ok=True)
for _f in ("tmp/managed_roles_api.db", "tmp/authz_audit.db"):
    if os.path.exists(_f):
        os.remove(_f)

# Every role/assignment change is written to an append-only audit table (the
# "who changed what, when" trail Casbin can't give you, since it never sees the
# acting principal). The admin's JWT sub is recorded as the actor.
audit = DbAuditSink(db_url="sqlite:///tmp/authz_audit.db")

# Define a starting admin + viewer. Everything else can be done over HTTP.
roles = ManagedRoleStore(db_url="sqlite:///tmp/managed_roles_api.db", audit=audit)
roles.set_role_scopes("viewer", ["agents:*:read"])
roles.set_role_scopes("admin", ["agent_os:admin"])
roles.assign("alice", "admin")
roles.assign("bob", "viewer")

# Setup database
db = SqliteDb(db_file="tmp/agentos.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
)

# Create AgentOS, then mount the admin management router.
agent_os = AgentOS(
    id=OS_ID,
    description="Managed-roles AgentOS with admin REST API",
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

app = agent_os.get_app()
app.include_router(get_roles_router(roles))  # the /authz management API


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run this file to walk the admin management API and print each result.

    Management endpoints (all admin-only, prefix /authz):
    - GET    /authz/roles                         list roles
    - PUT    /authz/roles/{role}                  set a role's scopes
    - DELETE /authz/roles/{role}                  delete a role
    - GET    /authz/users/{subject}/roles         a subject's roles
    - POST   /authz/users/{subject}/roles         grant a role
    - DELETE /authz/users/{subject}/roles/{role}  revoke a role

    alice is an admin, bob is a viewer. The scenario below has alice grant a
    'runner' role to bob over HTTP, shows bob gain run access live (same token),
    then revokes it again.
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
        print(f"  {label:48s} -> {r.status_code} {verdict}  {note}")

    print("\n" + "=" * 72)
    print("Managed roles admin API — running the scenario for you")
    print("=" * 72)
    show("alice (admin) GET    /authz/roles", client.get("/authz/roles", headers=auth("alice")), "admin")
    show("bob (viewer)  GET    /authz/roles", client.get("/authz/roles", headers=auth("bob")), "not admin -> blocked")
    show("anon          GET    /authz/roles", client.get("/authz/roles"), "no token -> 401")
    show("bob           POST   /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "viewer -> blocked")
    client.put("/authz/roles/runner", headers=auth("alice"), json={"scopes": ["agents:*:run"]})
    g = client.post("/authz/users/bob/roles", headers=auth("alice"), json={"role": "runner"})
    show("alice         POST   /authz/users/bob/roles", g, f"granted -> bob roles {g.json().get('roles')}")
    show("bob           POST   /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "after grant -> SAME token")
    client.delete("/authz/users/bob/roles/runner", headers=auth("alice"))  # revoke over HTTP
    show("alice         DELETE /authz/users/bob/roles/runner", client.get("/authz/users/bob/roles", headers=auth("alice")), "revoked -> bob back to viewer")
    show("bob           POST   /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "after revoke -> blocked again")
    print("=" * 72)

    # The append-only audit trail of everything the admin just did over HTTP.
    import sqlalchemy as sa

    print("\nAudit trail (authz_audit table, actor taken from the admin's jwt):")
    eng = sa.create_engine("sqlite:///tmp/authz_audit.db")
    with eng.connect() as conn:
        for row in conn.execute(
            sa.text("select actor, action, target, before, after from authz_audit order by id")
        ):
            actor = row.actor or "system"  # None = changed in code at startup, not via the api
            print(f"  {actor:6s} {row.action:18s} {row.target:8s} {row.before or '-'} -> {row.after or '-'}")
    print()
