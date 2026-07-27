"""
Scope-based RBAC for AgentOS (the default, no dependencies).

The simplest tier: permissions live as scope strings on the JWT, and AgentOS
enforces them on every request. Use this when whoever mints tokens can put the
right scopes on them and they rarely change.

Scopes are `resource:action` (e.g. `agents:read`) or `resource:id:action` for a
single resource (e.g. `agents:research-agent:run`). `agent_os:admin` allows
everything.

Run this file; it prints a token per persona. Call the API with one to see the
scope enforced:

    # carol can read but not run:
    curl http://localhost:7777/agents/research-agent -H "Authorization: Bearer <carol-token>"
    curl -X POST http://localhost:7777/agents/research-agent/runs \
         -H "Authorization: Bearer <carol-token>" -F "message=hi"   # -> 403

When you'd rather define/assign roles yourself and change them at runtime, see
managed_roles.py.
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
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

# Turn on authorization. With no custom provider, AgentOS uses the built-in
# scope provider: it reads the `scopes` claim off the verified JWT and checks it
# against the scope each route requires.
agent_os = AgentOS(
    description="AgentOS protected by JWT scopes",
    agents=[research_agent],
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
    ),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------


def make_token(sub: str, scopes: list[str]) -> str:
    """Mint a signed JWT carrying the caller's scopes."""
    payload = {
        "sub": sub,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


if __name__ == "__main__":
    """
    Run AgentOS with scope-based authorization.

    Each persona below gets a token carrying different scopes:
      carol (viewer) — agents:*:read           -> read works, run is 403
      bob   (member) — read + run this agent    -> read and run work
      alice (admin)  — agent_os:admin           -> everything works

    Test:
      curl http://localhost:7777/agents/research-agent -H "Authorization: Bearer <token>"
      curl -X POST http://localhost:7777/agents/research-agent/runs \
           -H "Authorization: Bearer <token>" -F "message=hi"
    """
    print("carol (viewer):", make_token("carol", ["agents:*:read"]))
    print(
        "bob   (member):",
        make_token("bob", ["agents:*:read", "agents:research-agent:run"]),
    )
    print("alice (admin) :", make_token("alice", ["agent_os:admin"]))
    agent_os.serve(app="scope_based_rbac:app", port=7777, reload=True)
