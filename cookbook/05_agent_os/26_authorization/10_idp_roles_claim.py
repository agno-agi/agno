"""
Roles on the token: Authorization(roles_claim=...) for an external identity provider

(New to this? Read 01_managed_roles.py first. 13_idp_workos_auth0.py shows the same IdP
setup with a custom provider and real RS256/JWKS verification; this file is the built-in
version of that integration.)

When WorkOS, Auth0 or Okta own your users, they already know each person's role and put it
on the token as a claim (Auth0 sends a list under "roles"; WorkOS sends one string under
"role"). You do not want to mirror every user into agno and `assign` them a role by hand.

`roles_claim` splits the work the natural way:

  - YOU define what each role may do, once, in code:   authz.define_role("member", [...])
  - THE TOKEN says which role the caller holds:        {"sub": "alice", "roles": ["member"]}

No per-user `assign` is needed. The role definitions live in your database, so the /authz
admin API can still edit what a role may do at runtime, and `audit=True` still records it.

Two details worth knowing:

  - A token whose claim names a role you never defined grants nothing (carol below).
  - A token with NO roles claim falls back to stored assignments, so `authz.assign` still
    works for the few subjects your IdP does not cover (erin below, and service accounts).
  - A caller whose token carries a role that grants `agent_os:admin` can use the /authz
    admin API, so "admin" can live in your IdP too (root below).

Run it:
    pip install "agno[os]"
    python 10_idp_roles_claim.py
(no external services and no model key: it decides who is allowed, without calling a model.)
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.authz import Authorization

# HS256 keeps this file self-contained. A real IdP signs with RS256 and publishes its keys;
# swap in jwks_file=... and issuer=... exactly as 13_idp_workos_auth0.py does.
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "idp-roles-claim-os"

os.makedirs("tmp", exist_ok=True)
if os.path.exists("tmp/idp_roles_claim.db"):
    os.remove("tmp/idp_roles_claim.db")

db = SqliteDb(db_file="tmp/idp_roles_claim.db")

# The integration: roles ride the token in the "roles" claim. Everything else is the same
# Authorization object as 01_managed_roles.py.
authz = Authorization(
    db=db,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    verify_audience=True,
    audience=OS_ID,
    roles_claim="roles",  # <- read the caller's role(s) from this claim
)
# What each role may do. The IdP never learns about scopes; it only names the role.
authz.define_role("admin", ["agent_os:admin"])
authz.define_role("member", ["agents:*:read", "agents:*:run"])
authz.define_role("viewer", ["agents:*:read"])
# A stored assignment for someone the IdP does not cover: it counts only when the token
# carries no roles claim at all.
authz.assign("erin", "viewer")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
)

agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS whose roles come from the identity provider",
    agents=[research_agent],
    db=db,
    authorization=authz,
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

    def token(sub: str, roles=None) -> str:
        """A token the way an IdP would mint it: identity plus the person's role(s)."""
        claims = {
            "sub": sub,
            "aud": OS_ID,
            "scopes": [],  # no agno scopes on the token; the ROLE decides
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        if roles is not None:
            claims["roles"] = roles
        return jwt.encode(claims, JWT_SECRET, algorithm="HS256")

    def show(label: str, tok: str, method: str, path: str, note: str = "") -> None:
        r = client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {tok}"},
            data={"message": "hi"},
        )
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:44s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 80)
    print("ROLES ON THE TOKEN - the IdP names the role, you define what it may do")
    print("=" * 80)
    print("  member = read + run | viewer = read | admin = the /authz admin API\n")

    # Auth0-style: a list. WorkOS-style: one string. Both are accepted.
    show(
        "alice (roles=['member']) RUN the agent",
        token("alice", ["member"]),
        "POST",
        "/agents/research-agent/runs",
        "members can run",
    )
    show(
        "bob   (roles='viewer')   LOOK at agent",
        token("bob", "viewer"),
        "GET",
        "/agents/research-agent",
        "viewers can read",
    )
    show(
        "bob   (roles='viewer')   RUN the agent",
        token("bob", "viewer"),
        "POST",
        "/agents/research-agent/runs",
        "viewers can't run -> bounced",
    )
    show(
        "carol (roles=['guest'])  LOOK at agent",
        token("carol", ["guest"]),
        "GET",
        "/agents/research-agent",
        "undefined role -> bounced",
    )
    show(
        "dave  (no roles claim)   LOOK at agent",
        token("dave"),
        "GET",
        "/agents/research-agent",
        "no claim, no assignment -> bounced",
    )
    show(
        "erin  (no roles claim)   LOOK at agent",
        token("erin"),
        "GET",
        "/agents/research-agent",
        "no claim -> stored assignment (viewer) decides",
    )
    show(
        "root  (roles=['admin'])  LIST /authz/roles",
        token("root", ["admin"]),
        "GET",
        "/authz/roles",
        "admin via the token's role",
    )
    show(
        "alice (roles=['member']) LIST /authz/roles",
        token("alice", ["member"]),
        "GET",
        "/authz/roles",
        "not an admin -> bounced",
    )

    print("=" * 80)
    print(
        "the point: define_role(...) once in code, and let the IdP say who holds which role."
    )
    print(
        "No per-user assign, and the /authz admin API still edits what each role may do."
    )
    print("=" * 80)
