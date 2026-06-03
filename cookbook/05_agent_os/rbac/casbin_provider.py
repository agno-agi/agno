"""
Advanced: using Casbin as the rules engine

(New to this? Read managed_roles.py first. This file is the power-user version of
the same idea and you probably don't need it day to day.)

Something has to actually decide "is this person allowed?". By default agno uses
its own simple rules engine. But agno lets you swap that engine out, so if a
customer already standardises on a well-known open-source one called Casbin, they
can plug it in without changing anything else about how AgentOS works.

This file does exactly that swap and then runs the same kind of check you saw in
managed_roles.py: a few people, a few requests, ALLOWED or BLOCKED for each. The
takeaway isn't the Casbin syntax, it's that the engine is replaceable while the
rest stays the same.

The cast:
- alice is a "member"  -> can look at agents and run the research agent
- root is an "admin"   -> can do anything
- mallory has no role  -> can do nothing

Run it:
    pip install "agno[casbin]"
    python casbin_provider.py
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

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "casbin-os"

os.makedirs("tmp", exist_ok=True)

# Casbin model + policy. In production, load policy from your DB with an adapter:
#   casbin.Enforcer(model, casbin_sqlalchemy_adapter.Adapter("postgresql://..."))
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
POLICY = """
p, member, agents/*, read
p, member, agents/research-agent, run
p, admin, agents/*, *
g, alice, member
g, root, admin
"""
with open("tmp/casbin_os_model.conf", "w") as f:
    f.write(MODEL)
with open("tmp/casbin_os_policy.csv", "w") as f:
    f.write(POLICY)
enforcer = casbin.Enforcer("tmp/casbin_os_model.conf", "tmp/casbin_os_policy.csv")

# Setup database
db = SqliteDb(db_file="tmp/agentos.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
)

# Create AgentOS, swapping in the Casbin-backed provider. One line.
agent_os = AgentOS(
    id=OS_ID,
    description="Casbin-protected AgentOS",
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
    Run this file to print Casbin's authorization decision for each caller.

    The policy above grants:
    - member  -> read all agents, run research-agent
    - admin   -> everything (agents/*, *)
    - alice is a member, root is an admin, anyone else has no role.

    Change roles at runtime via Casbin's management API, e.g.
        enforcer.add_role_for_user("bob", "member"); enforcer.save_policy()
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
        print(f"  {label:44s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 78)
    print("SAME CHECKS, DIFFERENT ENGINE (Casbin instead of agno's built-in)")
    print("=" * 78)
    print("  alice = member | root = admin | mallory = no role\n")
    show("alice (member)  tries to LOOK at the agent", client.get("/agents/research-agent", headers=auth("alice")), "members can look")
    show("alice (member)  tries to RUN the agent", client.post("/agents/research-agent/runs", headers=auth("alice"), data={"message": "hi"}), "members can run this one")
    show("mallory (none)  tries to LOOK at the agent", client.get("/agents/research-agent", headers=auth("mallory")), "no role -> bounced")
    show("root (admin)    tries to RUN the agent", client.post("/agents/research-agent/runs", headers=auth("root"), data={"message": "hi"}), "admins can do anything")
    print("=" * 78)
    print("the point: the decisions look identical to managed_roles.py - only the engine")
    print("underneath changed. that's the part worth seeing.")
    print("=" * 78)
