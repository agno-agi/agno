"""
Scenario 1 of 3: they HAVE a login service (e.g. WorkOS) - we only enforce

(New to this? Read managed_roles.py first.)

The three ways a company can run this:
  1. THIS FILE - they already use a login service (WorkOS, Okta, Auth0). It logs
     people in AND stamps each person's role on their token. We don't store any
     users or who-has-which-role; that's the login service's job. We only keep a
     tiny list of "what is each role allowed to do" and enforce it.
  2. no login service, they want us to manage users + roles  -> managed_roles_api.py
  3. a mix of both                                           -> casbin_external_idp.py

So in this scenario there is NO user database on our side. Nothing to store. The
token arrives already saying `role: "member"`, we look up what "member" can do,
and we allow or block. That's it.

The only thing we define is the role -> permissions list (here, in memory):
  - member -> can look at agents and run the research agent
  - admin  -> can do anything
WorkOS decides WHO is a member or admin; we decide what those words mean.

(Real WorkOS tokens are signed by WorkOS. In production you point agno at WorkOS's
live keys URL and it fetches + rotates them for you - no key file to manage:
    AuthorizationConfig(jwks_url="https://<your-workos>/.well-known/jwks.json", ...)
Here we use a simple shared secret so the example runs on its own; the
authorization behaviour is identical.)

Run it:
    pip install "agno[casbin]"
    python idp_enforce_only.py
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

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "idp-enforce-only-os"

os.makedirs("tmp", exist_ok=True)

# What each role is allowed to do. This is ALL we keep - no users, no assignments.
# It lives in memory (no database): roles are defined in code and never change here.
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
with open("tmp/idp_enforce_model.conf", "w") as f:
    f.write(MODEL)
enforcer = casbin.Enforcer("tmp/idp_enforce_model.conf")  # in-memory, no DB/adapter
enforcer.add_policy("member", "agents/*", "read")
enforcer.add_policy("member", "agents/research-agent", "run")
enforcer.add_policy("admin", "*", "*")
# Note: there are NO "who has which role" rows here. WorkOS owns that.

db = SqliteDb(db_file="tmp/agentos.db")
research_agent = Agent(id="research-agent", name="Research Agent", model=OpenAIChat(id="gpt-4o"), db=db)

agent_os = AgentOS(
    id=OS_ID,
    description="Enforce-only AgentOS (identity + roles come from the login service)",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        # roles_claim="role" -> read the person's role off the token (WorkOS puts
        # it in a claim called "role"). No store is consulted for assignments.
        authorization_provider=CasbinAuthorizationProvider(enforcer, roles_claim="role"),
    ),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)
    client = TestClient(app)

    def login_card(sub: str, role: str | None) -> str:
        # Stand-in for the token WorkOS would issue. The important part is the
        # `role` claim - that's the person's role, decided by the login service.
        claims = {"sub": sub, "aud": OS_ID, "exp": datetime.now(UTC) + timedelta(hours=24)}
        if role is not None:
            claims["role"] = role
        return jwt.encode(claims, JWT_SECRET, algorithm="HS256")

    def show(label: str, tok: str, method: str, path: str, note: str = "") -> None:
        r = client.request(method, path, headers={"Authorization": f"Bearer {tok}"}, data={"message": "hi"})
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:48s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 80)
    print("THEY HAVE A LOGIN SERVICE - WE ONLY ENFORCE (no user store on our side)")
    print("=" * 80)
    print("  the login service put each person's role on their token. we just read it.\n")

    show("alice (token says role=member) RUN agent", login_card("alice", "member"), "POST", "/agents/research-agent/runs", "member can run")
    show("alice (token says role=member) LOOK at agent", login_card("alice", "member"), "GET", "/agents/research-agent", "member can look")
    show("carol (token says role=guest)  LOOK at agent", login_card("carol", "guest"), "GET", "/agents/research-agent", "guest has no permissions -> bounced")
    show("dave  (token has no role)      LOOK at agent", login_card("dave", None), "GET", "/agents/research-agent", "no role on the token -> bounced")
    show("root  (token says role=admin)  RUN agent", login_card("root", "admin"), "POST", "/agents/research-agent/runs", "admin can do anything")
    print("=" * 80)
    print("the point: we stored no users and no assignments. WorkOS owns 'who is a")
    print("member'. we only own 'what a member can do', and we enforce it on every call.")
    print("=" * 80)
