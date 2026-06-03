"""
Turning someone's access on and off while the app is running

(New to this? Read managed_roles.py first.)

A real worry: someone leaves the company, or you grant access by mistake. Can you
cut their access RIGHT NOW, or do you have to wait for their login to expire?

With this setup the answer is "right now". The permissions live in your database,
not baked into the user's login card. So you can flip a person's access on or off
and their very next request obeys the new rule, even though they're still holding
the exact same card.

This file uses one person, bob, who starts with no access. We:
1. show bob is BLOCKED,
2. grant him access while the server runs -> he's now ALLOWED,
3. take it away again -> he's BLOCKED again,
all without bob logging in again or getting a new card.

Run it:
    pip install "agno[casbin]"
    python casbin_runtime_policy.py
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
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:34s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 78)
    print("TURNING ACCESS ON AND OFF, LIVE")
    print("=" * 78)
    print("  bob holds ONE login card the whole time. we never give him a new one.\n")

    show("bob asks to look at the agent", "starts with no access -> bounced")
    print("\n  >> grant bob access now (while the server is running)...\n")
    enforcer.add_role_for_user("bob", "member")
    show("bob asks again (same card)", "access flipped on -> he's in")
    print("\n  >> ...now cut his access...\n")
    enforcer.delete_role_for_user("bob", "member")
    show("bob asks again (same card)", "access flipped off -> bounced again")
    print("=" * 78)
    print("the point: you can revoke access instantly. bob never logged in again and")
    print("his card never changed - only the rule on the server side did.")
    print("=" * 78)
