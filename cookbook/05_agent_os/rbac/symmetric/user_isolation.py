"""
RBAC + Per-User Data Isolation Example with AgentOS

Builds on basic.py by opting in to per-user data isolation. With
``AuthorizationConfig(user_isolation=True)``:

- Non-admin JWT callers are scoped to their own ``sub`` user_id at the DB
  layer. /sessions, /memory, /traces only return rows they own; cancel /
  resume / continue routes require session_id and verify run ownership.
- A caller with the configured ``admin_scope`` (default ``agent_os:admin``)
  bypasses isolation entirely and sees everyone's data — same as before.

JWT/RBAC is unchanged from basic.py. Isolation is the new layer on top.

Prerequisites:
- Set JWT_VERIFICATION_KEY or pass it to AuthorizationConfig
- Postgres reachable at postgresql+psycopg://ai:ai@localhost:5532/ai
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# user_isolation=True is the only difference from basic.py.
# admin_scope is left at the default ("agent_os:admin"); set it explicitly
# if you want a custom override, e.g. admin_scope="ops:admin".
agent_os = AgentOS(
    id="my-agent-os",
    description="RBAC + Per-User Isolation AgentOS",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        user_isolation=True,
    ),
)

app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------


def _mint(sub: str, scopes: list[str]) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "aud": "my-agent-os",
            "scopes": scopes,
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


if __name__ == "__main__":
    """
    With user_isolation=True:

    Isolation matrix
    ----------------
    Caller                                  | Sees
    ----------------------------------------|-------------------------
    No JWT                                  | everything (isolation needs a JWT user_id)
    JWT with `agent_os:admin`               | everything (admin bypass)
    JWT without admin scope                 | only rows where user_id == JWT sub

    Cancel / resume / continue:
    - Admin: no session_id required (legacy behaviour).
    - Non-admin: must pass session_id; the run must live in a session the
      caller owns, otherwise 404.

    The admin scope is configurable via AuthorizationConfig(admin_scope="…").
    Once overridden, the default `agent_os:admin` stops granting bypass.
    """
    user_a_token = _mint("user-a", ["agents:read", "agents:run", "sessions:read"])
    user_b_token = _mint("user-b", ["agents:read", "agents:run", "sessions:read"])
    admin_token = _mint("admin-1", ["agent_os:admin"])

    print("\n" + "=" * 60)
    print("Isolation Test Tokens")
    print("=" * 60)
    print("\nuser-a (non-admin) — sees only user-a's sessions/memory/traces:")
    print(user_a_token)
    print("\nuser-b (non-admin) — sees only user-b's sessions/memory/traces:")
    print(user_b_token)
    print("\nadmin-1 (agent_os:admin) — bypasses isolation, sees everyone:")
    print(admin_token)

    print("\n" + "=" * 60)
    print("Demo")
    print("=" * 60)
    print("\n# 1. user-a starts a run (creates a session attributed to user-a)")
    print(
        '\ncurl -X POST -H "Authorization: Bearer '
        + user_a_token
        + '" -F "message=hello from a" http://localhost:7777/agents/research-agent/runs'
    )

    print("\n# 2. user-b starts a run (creates a session attributed to user-b)")
    print(
        '\ncurl -X POST -H "Authorization: Bearer '
        + user_b_token
        + '" -F "message=hello from b" http://localhost:7777/agents/research-agent/runs'
    )

    print("\n# 3. user-a lists sessions — only their own row comes back")
    print(
        '\ncurl -H "Authorization: Bearer '
        + user_a_token
        + '" "http://localhost:7777/sessions?type=agent"'
    )

    print("\n# 4. admin lists sessions — both rows come back")
    print(
        '\ncurl -H "Authorization: Bearer '
        + admin_token
        + '" "http://localhost:7777/sessions?type=agent"'
    )

    print("\n# 5. user-a cancels their own run (session_id required)")
    print(
        '\ncurl -X POST -H "Authorization: Bearer '
        + user_a_token
        + '" "http://localhost:7777/agents/research-agent/runs/<RUN_ID>/cancel?session_id=<USER_A_SESSION_ID>"'
    )

    print("\n# 6. user-a tries to cancel a run in user-b's session — 404")
    print(
        '\ncurl -X POST -H "Authorization: Bearer '
        + user_a_token
        + '" "http://localhost:7777/agents/research-agent/runs/<RUN_ID>/cancel?session_id=<USER_B_SESSION_ID>"'
    )
    print("\n" + "=" * 60 + "\n")

    agent_os.serve(app="user_isolation:app", port=7777, reload=True)
