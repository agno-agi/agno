"""
Casbin Runtime Policy Example with AgentOS

This example demonstrates policy stored in YOUR database and changed live, with no
token re-mint. Grant or revoke a role at runtime and the very next request reflects
it, using the same token. Policy persists in your own DB (here SQLite via the
SQLAlchemy adapter; in production point it at Postgres).

This is what token-baked scopes cannot do: revoking a scope in a token means
waiting for the token to expire. With DB-backed Casbin, "revoke now" is now.

Prerequisites:
- pip install "agno[casbin]"
- Set OPENAI_API_KEY to actually run an agent (authorization is enforced regardless)
"""

import os
from datetime import UTC, datetime, timedelta

import casbin
import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.authz.casbin_provider import CasbinAuthorizationProvider
from agno.os.config import AuthorizationConfig
from casbin_sqlalchemy_adapter import Adapter

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "casbin-runtime-os"
POLICY_DB_URL = "sqlite:///tmp/casbin_policy.db"
MODEL_PATH = "tmp/casbin_runtime_model.conf"

os.makedirs("tmp", exist_ok=True)

MODEL = """
[request_definition]
r = sub, obj, act
[policy_definition]
p = sub, obj, act
[role_definition]
g = _, _
[policy_effect]
e = some(where (p.eft == allow))
[matchers]
m = g(r.sub, p.sub) && keyMatch2(r.obj, p.obj) && (r.act == p.act || p.act == "*")
"""
with open(MODEL_PATH, "w") as f:
    f.write(MODEL)

# Policy lives in YOUR DB via the SQLAlchemy adapter. Use a Postgres URL in prod.
enforcer = casbin.Enforcer(MODEL_PATH, Adapter(POLICY_DB_URL))
enforcer.enable_auto_save(True)  # mutations persist to the DB immediately
# Seed: member may read+run the research agent. bob starts with NO role.
enforcer.add_policy("member", "agents/research-agent", "read")
enforcer.add_policy("member", "agents/research-agent", "run")

# Setup database
db = SqliteDb(db_file="tmp/agentos.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
)

# Create AgentOS using the DB-backed Casbin enforcer.
agent_os = AgentOS(
    id=OS_ID,
    description="Casbin AgentOS with runtime-mutable policy",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        authorization_provider=CasbinAuthorizationProvider(enforcer),
    ),
)

# Get the app
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run this file to watch DB-backed policy change at runtime.

    bob's token never changes; only the policy in tmp/casbin_policy.db does. The
    scenario below grants bob the member role, shows his access flip to 200, then
    revokes it and shows it flip back to 403, all with the same token.
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

    bob_h = {"Authorization": f"Bearer {token('bob')}"}

    def show(label: str, note: str = "") -> None:
        r = client.get("/agents/research-agent", headers=bob_h)
        verdict = "DENIED " if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:42s} -> {r.status_code} {verdict}  {note}")

    print("\n" + "=" * 70)
    print("Casbin runtime policy — running the scenario for you")
    print("(bob's token NEVER changes; only the DB-backed policy does)")
    print("=" * 70)
    show("bob GET /agents/research-agent", "no role yet -> blocked")
    enforcer.add_role_for_user("bob", "member")  # grant at runtime, persists to the DB
    show("bob GET /agents/research-agent", "granted 'member' live -> SAME token")
    enforcer.delete_role_for_user("bob", "member")  # revoke at runtime
    show("bob GET /agents/research-agent", "revoked live -> blocked again")
    print("=" * 70)
