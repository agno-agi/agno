"""
Managed Users - a user directory for AgentOS, no identity provider needed

Already did managed_roles.py? That showed ROLES (who can do what). This shows
USERS (who exists), for the case where you DON'T have an external login system
(no Okta/Auth0/WorkOS). Your own app still signs people in its own way and hands
them a token; AgentOS keeps the list of users and decides what they can do.

Important: AgentOS does NOT store passwords and does not log anyone in. It keeps
a directory - just id, optional email/name, and an on/off switch per person -
plus their roles. Think "address book with an off switch", not "login system".

Why bother keeping users at all (instead of only roles)?
1. You can SEE everyone who exists and pick a person to give a role to, instead
   of typing a raw id you have to remember.
2. You get a real OFF SWITCH. Disable someone and their very next request is
   blocked - even though their token is still valid and unexpired. A token alone
   can't be "un-issued"; the directory can.
3. The audit trail can say "bob@co" instead of an opaque id.

This file creates a few users, gives them roles, then:
- lists the directory,
- shows bob working normally,
- DISABLES bob and shows his next request bounce (same valid token),
- re-enables him.

Run it:
    pip install "agno[roles]"
    python managed_users.py
(no OpenAI key needed - we are only checking who is allowed, not chatting)
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.authz.role_router import get_roles_router
from agno.os.authz.role_store import ManagedRoleStore
from agno.os.authz.user_store import ManagedUserStore
from agno.os.config import AuthorizationConfig

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "managed-users-os"

os.makedirs("tmp", exist_ok=True)

# Roles: what each role can do (same as managed_roles.py).
roles = ManagedRoleStore(db_url="sqlite:///tmp/managed_users_roles.db")
roles.set_role_scopes("viewer", ["agents:*:read"])
roles.set_role_scopes("admin", ["agent_os:admin"])

# Users: the directory. Just people, no passwords. We give each one a role too.
users = ManagedUserStore(db_url="sqlite:///tmp/managed_users.db")
users.upsert("alice", email="alice@co", name="Alice")
roles.assign("alice", "admin")
users.upsert("bob", email="bob@co", name="Bob")
roles.assign("bob", "viewer")

db = SqliteDb(db_file="tmp/managed_users_agentos.db")
research_agent = Agent(id="research-agent", name="Research Agent", model=OpenAIChat(id="gpt-4o"), db=db)

# Wire BOTH stores into AgentOS. user_store= turns on the directory + off-switch.
agent_os = AgentOS(
    id=OS_ID,
    description="Managed-users AgentOS",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        authorization_provider=roles.provider,
        user_store=users,  # <- the directory + disabled kill-switch
    ),
)
app = agent_os.get_app()
# Expose the admin HTTP API for managing users (/authz/users) and roles.
app.include_router(get_roles_router(roles, user_store=users))


if __name__ == "__main__":
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
        print(f"  {label:48s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 80)
    print("A USER DIRECTORY - no identity provider, just AgentOS")
    print("=" * 80)

    # The admin can list everyone in the directory, with their roles merged in.
    print("\n  the directory (asked for by alice, an admin):")
    listing = client.get("/authz/users", headers=auth("alice")).json()["users"]
    for u in listing:
        print(f"    - {u['id']:8s} {str(u['email'] or ''):12s} roles={u['roles']}  disabled={u['disabled']}")

    print("\n  bob is a viewer, so he can look at the agent:")
    show("bob asks to LOOK at the agent", client.get("/agents/research-agent", headers=auth("bob")), "viewers can look")

    print("\n  >> now an admin DISABLES bob (e.g. he left the company)...\n")
    client.post("/authz/users/bob/disable", headers=auth("alice"))
    show("bob asks to LOOK at the agent", client.get("/agents/research-agent", headers=auth("bob")), "same valid token, but he's blocked now")

    print("\n  >> ...bob is back, re-enable him...\n")
    client.post("/authz/users/bob/enable", headers=auth("alice"))
    show("bob asks to LOOK at the agent", client.get("/agents/research-agent", headers=auth("bob")), "allowed again, instantly")

    print("=" * 80)
    print("the point: you keep the list of users and an off-switch per person. disabling")
    print("someone blocks their NEXT request even though their token is still valid -")
    print("something you can't do with tokens alone. no passwords are ever stored here.")
    print("=" * 80)
