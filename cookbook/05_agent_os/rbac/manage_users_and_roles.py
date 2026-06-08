"""
Managing users AND roles over HTTP - the full admin flow (no login service)

(New to this? Read managed_roles.py first, then managed_users.py.)

This is the one-stop "admin console" cookbook for the no-login-service case. It
drives EVERYTHING an admin would do, entirely over the HTTP API that ships with
AgentOS (the /authz endpoints):

  - define what a role can do          PUT    /authz/roles/{role}
  - add a user to the directory        POST   /authz/users
  - give a user a role                 POST   /authz/users/{id}/roles
  - list users (with their roles)      GET    /authz/users
  - disable / re-enable a user         POST   /authz/users/{id}/disable | /enable
  - read the audit trail               GET    /authz/audit

Every one of those endpoints is admin-only. We seed a single bootstrap admin in
code (someone has to be able to log in first); everything after that is done over
HTTP, exactly as your own admin UI or scripts would.

What you'll see, in order:
  1. only an admin can touch the management API (a normal user is bounced)
  2. an admin builds roles + users + assignments live
  3. those permissions actually take effect (bob can read, carol can run)
  4. the disable kill-switch: a disabled user is blocked on their next request
     even though their token is still valid
  5. the audit trail of every change, who made it, before -> after

Run it:
    pip install "agno[roles]"
    python manage_users_and_roles.py
(no OpenAI key needed - we only check who is allowed, we don't actually chat.)
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
from agno.os.authz.user_store import ManagedUserStore
from agno.os.config import AuthorizationConfig

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "admin-console-os"

os.makedirs("tmp", exist_ok=True)
for _f in ("roles.db", "users.db", "audit.db", "agentos.db"):
    p = f"tmp/console_{_f}"
    if os.path.exists(p):
        os.remove(p)

# One audit sink shared by both stores so the trail covers role AND user changes.
audit = DbAuditSink(db_url="sqlite:///tmp/console_audit.db")
roles = ManagedRoleStore(db_url="sqlite:///tmp/console_roles.db", audit=audit)
users = ManagedUserStore(db_url="sqlite:///tmp/console_users.db", audit=audit)

# Bootstrap: one admin who can use the management API. Everything else is done
# over HTTP below. (In production you'd seed this once at deploy time.)
roles.set_role_scopes("admin", ["agent_os:admin"])
roles.assign("alice", "admin")
users.upsert("alice", email="alice@co", name="Alice (admin)")

db = SqliteDb(db_file="tmp/console_agentos.db")
research_agent = Agent(id="research-agent", name="Research Agent", model=OpenAIChat(id="gpt-4o"), db=db)

agent_os = AgentOS(
    id=OS_ID,
    description="Admin console AgentOS (manage users + roles over HTTP)",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        authorization_provider=roles.provider,
        user_store=users,
        audit=audit,
    ),
)
app = agent_os.get_app()
app.include_router(get_roles_router(roles, user_store=users))


if __name__ == "__main__":
    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)
    client = TestClient(app)

    def auth(sub: str) -> dict:
        tok = jwt.encode(
            {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=8)},
            JWT_SECRET, algorithm="HS256",
        )
        return {"Authorization": f"Bearer {tok}"}

    def show(label, r, note=""):
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:50s} -> {verdict:7s} ({r.status_code})  {note}")

    A = auth("alice")  # the bootstrap admin

    print("\n" + "=" * 84)
    print("ADMIN CONSOLE - managing users + roles entirely over HTTP")
    print("=" * 84)

    print("\n1) only an admin can use the management API:")
    show("alice (admin) lists users", client.get("/authz/users", headers=A), "admins can")
    show("bob (not even created yet) lists users", client.get("/authz/users", headers=auth("bob")), "non-admin -> bounced")
    show("anonymous lists users", client.get("/authz/users"), "not logged in -> bounced harder")

    print("\n2) alice builds roles, users, and assignments - all over HTTP:")
    client.put("/authz/roles/viewer", headers=A, json={"scopes": ["agents:*:read"]})
    client.put("/authz/roles/runner", headers=A, json={"scopes": ["agents:*:read", "agents:*:run"]})
    print("   created roles: viewer (read), runner (read+run)")
    client.post("/authz/users", headers=A, json={"id": "bob", "email": "bob@co", "name": "Bob"})
    client.post("/authz/users", headers=A, json={"id": "carol", "email": "carol@co", "name": "Carol"})
    client.post("/authz/users/bob/roles", headers=A, json={"role": "viewer"})
    client.post("/authz/users/carol/roles", headers=A, json={"role": "runner"})
    print("   added users bob (viewer) and carol (runner)\n")

    for u in client.get("/authz/users", headers=A).json()["users"]:
        print(f"     - {u['id']:8s} {str(u['email'] or ''):12s} roles={u['roles']}  disabled={u['disabled']}")

    print("\n3) the permissions actually take effect:")
    show("bob (viewer) LOOK at agent", client.get("/agents/research-agent", headers=auth("bob")), "viewers can look")
    show("bob (viewer) RUN agent", client.post("/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}), "viewers can't run -> bounced")
    show("carol (runner) RUN agent", client.post("/agents/research-agent/runs", headers=auth("carol"), data={"message": "hi"}), "runners can run")

    print("\n4) the disable kill-switch (bob leaves the company):")
    client.post("/authz/users/bob/disable", headers=A)
    show("bob LOOK at agent (now disabled)", client.get("/agents/research-agent", headers=auth("bob")), "blocked on his next request, same token")
    client.post("/authz/users/bob/enable", headers=A)
    show("bob LOOK at agent (re-enabled)", client.get("/agents/research-agent", headers=auth("bob")), "allowed again, instantly")

    print("\n5) the audit trail - every change, who did it, before -> after:")
    for e in reversed(client.get("/authz/audit", headers=A).json()["events"]):
        before = e.get("before")
        after = e.get("after")
        diff = f"{before} -> {after}" if (before is not None or after is not None) else ""
        print(f"     {str(e['actor'] or 'system'):7s} {e['action']:18s} {e['target']:8s} {diff}")

    print("=" * 84)
    print("the point: one admin bootstrapped in code; everything else - roles, users,")
    print("assignments, disabling - done over the same /authz HTTP API your console would")
    print("use, admin-only, with a full audit trail. no login service, no passwords stored.")
    print("=" * 84)
