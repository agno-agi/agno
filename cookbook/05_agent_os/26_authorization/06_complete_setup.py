"""
The complete built-in setup on one page - roles, users, audit and the admin API together

(Read 01_managed_roles.py to 05_managed_roles_audit.py first; each of those introduces one
piece. This file puts every piece together the way a real deployment wires them, and
07_manage_users_and_roles.py serves exactly this setup for a frontend.)

What is on the page:

1. A user directory (the roster), seeded with three people and set to auto-provision anyone
   else who arrives with a valid token.
2. Roles: admin, viewer (the default a brand-new user gets) and runner, with alice bootstrapped
   as the admin and the others handed a role. Safe to run on every start.
3. The audit trail, on with one switch.
4. Two enforcement planes at once: the managed roles for end users, and the token's own scopes
   for an operator token minted elsewhere (trust_token_scopes=True).
5. The admin API, mounted for you: /authz for roles and /users for the directory.

Permissions are written as "scopes":
- "agents:*:read"             -> can look at any agent
- "agents:research:run"       -> can run the one agent called research
- "agent_os:admin"            -> can do everything

Run it:
    pip install "agno[os]"
    python 06_complete_setup.py
(no OpenAI key needed here - we only check who is allowed, not actually chat)
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.authz import Authorization, UserDirectory

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "authz-complete-setup-os"

os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/authz_complete_setup.db")

# The user directory (roster) is separate from authorization: create the store and seed people on it.
users = UserDirectory(db=db, auto_provision=True)
users.upsert("alice", email="alice@example.com", name="Alice")
users.upsert("bob", email="bob@example.com", name="Bob")
users.upsert("carol", email="carol@example.com", name="Carol")

# Authorization is verification + roles + the admin bootstrap. It borrows the AgentOS db below, turns
# on the audit trail, and runs a token-scope plane next to the roles so an operator token works too.
authz = Authorization(
    db=db,
    audit=True,
    trust_token_scopes=True,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",  # matches how the tokens below are signed
    audience=OS_ID,
    verify_audience=True,
)

# Define the roles. "default=True" is what a brand-new user gets on first sign-in.
authz.define_role("admin", ["agent_os:admin"])
authz.define_role("viewer", ["agents:*:read"], default=True)
authz.define_role("runner", ["agents:*:read", "agents:*:run"])

# Bootstrap the admin ROLE, then hand roles to the seeded users. Safe to run on every start.
authz.seed(admin="alice")  # alice is the bootstrap admin
authz.assign(
    "bob", "viewer"
)  # bootstrap-safe: a runtime role change survives a restart
authz.assign("carol", "runner")

agent_os = AgentOS(
    id=OS_ID,
    db=db,
    agents=[
        Agent(
            id="research",
            name="Research",
            model=OpenAIResponses(id="gpt-5.6-luna"),
            db=db,
        ),
        Agent(
            id="vault", name="Vault", model=OpenAIResponses(id="gpt-5.6-luna"), db=db
        ),
    ],
    # The user directory is a top-level switch (a peer of user_isolation). Pass the store you seeded;
    # auto_provision creates + default-roles an unknown but authenticated user on first request.
    user_directory=users,
    authorization=authz,
)
app = agent_os.get_app()


if __name__ == "__main__":
    from fastapi.testclient import TestClient

    client = TestClient(app)

    def auth(sub: str, scopes=None) -> dict:
        payload = {
            "sub": sub,
            "aud": OS_ID,
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        if scopes is not None:
            payload["scopes"] = scopes
        return {
            "Authorization": f"Bearer {jwt.encode(payload, JWT_SECRET, algorithm='HS256')}"
        }

    def verdict(r) -> str:
        # We only care about the authorization decision, not whether the run itself succeeds,
        # so anything that is not a 401/403 counts as ALLOWED (a run may 500 with no model key).
        return "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"

    def show(label: str, r) -> None:
        print(f"  {verdict(r):8} {label}")

    print("\nEach person makes a real request. ALLOWED = got in, BLOCKED = bounced.\n")
    show(
        "alice (admin) runs vault",
        client.post(
            "/agents/vault/runs", headers=auth("alice"), data={"message": "hi"}
        ),
    )
    show(
        "carol (runner) runs research",
        client.post(
            "/agents/research/runs", headers=auth("carol"), data={"message": "hi"}
        ),
    )
    show(
        "bob (viewer) reads research",
        client.get("/agents/research", headers=auth("bob")),
    )
    show(
        "bob (viewer) runs research",
        client.post(
            "/agents/research/runs", headers=auth("bob"), data={"message": "hi"}
        ),
    )
    show(
        "dave (unknown) reads research",
        client.get("/agents/research", headers=auth("dave")),
    )
    show(
        "operator token (agent_os:admin scope, no role) runs vault",
        client.post(
            "/agents/vault/runs",
            headers=auth("op", scopes=["agent_os:admin"]),
            data={"message": "hi"},
        ),
    )

    print("\nThe admin API is mounted for you (no include_router):")
    show(
        "alice lists roles at /authz/roles",
        client.get("/authz/roles", headers=auth("alice")),
    )
    show("alice lists users at /users", client.get("/users", headers=auth("alice")))
    show("bob (not admin) lists roles", client.get("/authz/roles", headers=auth("bob")))
    print()
