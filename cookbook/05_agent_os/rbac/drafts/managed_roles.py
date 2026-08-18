"""
Managed roles for AgentOS — define roles, assign them, change them at runtime.

The middle tier: instead of putting scopes on every token, you define roles in
your own database and assign people to them. A token only needs to say *who* the
caller is (the `sub` claim); their permissions come from the role you gave them.
Change a role or an assignment and it takes effect on the next request — no token
re-issue, no redeploy. Roles are written in agno scope terms; the decision engine
is agno's own (no third-party policy engine).

A database is required (roles must persist and stay consistent across replicas).

Run this file; it prints a token per persona. Call the API with one to see the
role enforced:

    # carol (viewer) can read but not run:
    curl http://localhost:7777/agents/research-agent -H "Authorization: Bearer <carol-token>"
    curl -X POST http://localhost:7777/agents/research-agent/runs \
         -H "Authorization: Bearer <carol-token>" -F "message=hi"   # -> 403

For roles that already ride the token from an external IdP (WorkOS/Auth0/Okta),
see idp_workos_auth0.py. For scopes-on-the-token only, see scope_based_rbac.py.
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.authz.role_store import ManagedRoleStore
from agno.os.config import AuthorizationConfig

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT secret (use an environment variable in production).
JWT_SECRET = "a-string-secret-at-least-256-bits-long"

# Setup the database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
)

# Define the roles (in agno scope terms) and assign people to them. This is the
# whole authorization model — it persists to `db` and is fully runtime-mutable:
# call roles.set_role_scopes(...) / roles.assign(...) later and the change is live
# on the next request.
roles = ManagedRoleStore(db=db)
roles.set_role_scopes("viewer", ["agents:*:read"])
roles.set_role_scopes("member", ["agents:*:read", "agents:research-agent:run"])
roles.set_role_scopes("admin", ["agent_os:admin"])
roles.assign("carol", "viewer")
roles.assign("bob", "member")
roles.assign("alice", "admin")

# Wire the store into AgentOS. `role_store=` is the shortcut: AgentOS uses the
# store's authorization provider for you.
agent_os = AgentOS(
    description="AgentOS protected by managed roles",
    agents=[research_agent],
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        role_store=roles,
    ),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------


def make_token(sub: str) -> str:
    """Mint a signed JWT that only identifies the caller — no scopes. Permissions
    come from the role assigned to this subject in the store."""
    payload = {
        "sub": sub,
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


if __name__ == "__main__":
    """
    Run AgentOS with managed-role authorization.

    The tokens carry no scopes — permissions come from each subject's role:
      carol (viewer) — read works, running is 403
      bob   (member) — read and run research-agent
      alice (admin)  — everything

    Test:
      curl http://localhost:7777/agents/research-agent -H "Authorization: Bearer <token>"
      curl -X POST http://localhost:7777/agents/research-agent/runs \
           -H "Authorization: Bearer <token>" -F "message=hi"

    Try it live: while the server runs, grant bob admin from a Python shell —
      ManagedRoleStore(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai").assign("bob", "admin")
    — and bob's next request is allowed, with the same token.
    """
    print("carol (viewer):", make_token("carol"))
    print("bob   (member):", make_token("bob"))
    print("alice (admin) :", make_token("alice"))
    agent_os.serve(app="managed_roles:app", port=7777, reload=True)
