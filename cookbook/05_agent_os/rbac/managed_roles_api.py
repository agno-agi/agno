"""
Scenario 2 of 3: NO login service - they want US to manage users and roles

(If roles are new to you, read managed_roles.py first.)

The three ways a company can run this:
  1. they already have a login service, we only enforce  -> idp_enforce_only.py
  2. THIS FILE - no login service, we manage users + roles ourselves
  3. a mix of both                                        -> casbin_external_idp.py

In this scenario the company has no WorkOS/Okta. Their own app logs people in and
issues them a token that just says who they are. Everything about permissions
lives with US: we hold the list of roles, who has which role, and we let admins
change it. (We are not doing the login itself - no passwords or MFA - just the
"what are you allowed to do" part, which is what they asked us to provide.)

So this file adds a small set of web endpoints (a REST API) for managing all of
that while the app runs: create a role, give it to someone, take it away - over
plain HTTP.

Two important things this shows:

1. Only admins can use these endpoints. If a normal user calls them they get
   BLOCKED, and someone with no login at all is bounced even harder. So the tool
   that hands out power is itself protected.

2. Every change is written to an audit log: a permanent, append-only record of
   who changed what and when (e.g. "alice gave bob the runner role"). This is the
   kind of trail a security/compliance review asks for. At the end the file prints
   that log so you can see it.

The endpoints all live under /authz, for example:
    GET    /authz/roles                  -> list the roles
    PUT    /authz/roles/{role}           -> set what a role can do
    POST   /authz/users/{who}/roles      -> give someone a role
    DELETE /authz/users/{who}/roles/{r}  -> take a role away

Run it:
    pip install "agno[casbin]"
    python managed_roles_api.py
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
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:46s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 80)
    print("MANAGING ROLES OVER THE WEB (and who's allowed to)")
    print("=" * 80)
    print("  alice = admin (allowed to manage) | bob = normal user | anon = nobody logged in\n")

    print("  first, who can even use the management endpoints?")
    show("alice (admin) opens the roles admin", client.get("/authz/roles", headers=auth("alice")), "admins can")
    show("bob (normal)  opens the roles admin", client.get("/authz/roles", headers=auth("bob")), "normal users can't -> bounced")
    show("nobody        opens the roles admin", client.get("/authz/roles"), "not logged in -> bounced harder")

    print("\n  now watch alice give bob a new power, live:")
    show("bob tries to RUN an agent (before)", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "bob can't run yet")
    client.put("/authz/roles/runner", headers=auth("alice"), json={"scopes": ["agents:*:run"]})
    print("    (alice created a 'runner' role that can run agents)")
    client.post("/authz/users/bob/roles", headers=auth("alice"), json={"role": "runner"})
    print("    (alice gave bob the 'runner' role)")
    show("bob tries to RUN an agent (after)", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "same bob, now allowed")
    client.delete("/authz/users/bob/roles/runner", headers=auth("alice"))
    print("    (alice took the 'runner' role back)")
    show("bob tries to RUN an agent (after revoke)", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "bounced again")
    print("=" * 80)

    # Every change above was written to a permanent record. Here it is.
    import sqlalchemy as sa

    print("\nTHE RECORD: every change is logged - who did it, what changed, before -> after.")
    print("(this is what a security review wants to see)")
    eng = sa.create_engine("sqlite:///tmp/authz_audit.db")
    with eng.connect() as conn:
        for row in conn.execute(
            sa.text("select actor, action, target, before, after from authz_audit order by id")
        ):
            actor = row.actor or "system"  # None = changed in code at startup, not via the api
            print(f"  {actor:6s} {row.action:18s} {row.target:8s} {row.before or '-'} -> {row.after or '-'}")
    print()
