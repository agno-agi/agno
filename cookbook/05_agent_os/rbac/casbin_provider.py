"""
Casbin Authorization Provider Example with AgentOS

This example demonstrates how to swap the default scope matcher for a Casbin
enforcer behind the authorization provider seam, so you get role hierarchy,
wildcards, and policy stored/edited in your own DB. Casbin is a pure-Python
library (no service); the default provider stays the zero-dependency scope
matcher, this is opt-in.

Policy convention (Casbin `p = sub, obj, act`): sub is the JWT `sub`, obj is
"<resource_type>/<resource_id>" (use keyMatch2 for wildcards), act is the action.
Roles via `g, user, role`. In production point the enforcer's adapter at your DB.

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
        verdict = "DENIED " if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:48s} -> {r.status_code} {verdict}  {note}")

    print("\n" + "=" * 70)
    print("Casbin RBAC — running the scenario for you")
    print("=" * 70)
    show("alice (member) GET  /agents/research-agent", client.get("/agents/research-agent", headers=auth("alice")), "can read")
    show("alice (member) POST /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("alice"), data={"message": "hi"}), "can run")
    show("mallory (none) GET  /agents/research-agent", client.get("/agents/research-agent", headers=auth("mallory")), "no role -> blocked")
    show("root (admin)   POST /agents/research-agent/runs", client.post("/agents/research-agent/runs", headers=auth("root"), data={"message": "hi"}), "admin -> all")
    print("=" * 70)
