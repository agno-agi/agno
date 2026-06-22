"""
Managed Roles - controlling who can do what in AgentOS

New to this? Start with this file. "Authorization" just means deciding who is
allowed to do what. Two pieces make it work:

1. A token. When a user signs in they get a token: a small signed ID card they
   send with every request. It says who they are (e.g. "bob") and can't be faked.
2. Permissions. On the AgentOS side you decide what each person can do, like
   "can look at agents" or "can run the research agent".

Listing permissions per person gets messy fast, so we use ROLES: a named bundle
of permissions. You say once what a role can do ("a viewer can read"), then hand
people roles ("bob is a viewer"). Change the role and everyone with it changes too.

Permissions are written in a short code called a "scope":
- "agents:*:read"              -> can look at any agent
- "agents:research-agent:run"  -> can run the one agent called research-agent
- "agent_os:admin"             -> can do everything (a super-admin)

This file creates three roles and two people, then makes real requests and prints
ALLOWED or BLOCKED for each. It also shows the neat part: you can change someone's
role while the server is running and their very next request reflects it, with no
new login and no new token.

Run it:
    pip install "agno[roles]"
    python managed_roles.py
(no OpenAI key needed here - we are only checking who is allowed, not actually chatting)
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
        # 200 means the request got in; 401/403 means it was bounced.
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:46s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 78)
    print("WHO CAN DO WHAT - three roles, two people")
    print("=" * 78)
    print("  roles:  viewer = look at agents | member = look + run | admin = anything")
    print("  people: bob is a viewer         | alice is an admin")
    print(
        "  below, each person makes a real request. ALLOWED = got in, BLOCKED = bounced.\n"
    )

    show(
        "bob (viewer)  asks to LOOK at the agent",
        client.get("/agents/research-agent", headers=auth("bob")),
        "viewers can look",
    )
    show(
        "bob (viewer)  asks to RUN the agent",
        client.post(
            "/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}
        ),
        "viewers can't run, so he's bounced",
    )

    print("\n  >> now we make bob a 'member' while the server is running...\n")
    roles.assign("bob", "member")
    show(
        "bob (member)  asks to RUN the agent",
        client.post(
            "/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}
        ),
        "same bob, same token, now allowed",
    )

    print("\n  >> ...and now we take the 'member' role back...\n")
    roles.unassign("bob", "member")
    show(
        "bob (no role) asks to RUN the agent",
        client.post(
            "/agents/research-agent/runs", headers=auth("bob"), data={"message": "hi"}
        ),
        "bounced again, instantly",
    )

    show(
        "alice (admin) asks to RUN the agent",
        client.post(
            "/agents/research-agent/runs", headers=auth("alice"), data={"message": "hi"}
        ),
        "admins can do anything",
    )
    print("=" * 78)
    print(
        "the point: you control access by handing out roles, and a change takes effect"
    )
    print("on the very next request - no new login, no new token.")
    print("=" * 78)
