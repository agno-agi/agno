"""
Scenario 3 of 3: a MIX - some users from a login service, some managed by us

(New to this? Read managed_roles.py first.)

The three ways a company can run this:
  1. they already have a login service, we only enforce  -> idp_enforce_only.py
  2. no login service, they want us to manage it          -> managed_roles_api.py
  3. THIS FILE - a mix of both, at the same time

Why a mix happens: a company's employees log in through WorkOS/Okta (so their
role rides their token), but they also have external partners or service accounts
that don't exist in WorkOS, so WE manage those in our own list. One AgentOS has
to handle both. It does, with one simple rule:

  if the token already carries a role, use it (that's the login-service user).
  if it doesn't, fall back to our own list of who-has-which-role.

So the same agent is protected the same way no matter where the user came from.

The cast (all asking to look at the research agent):
- alice -> from the login service, token says role "member"      -> allowed
- carol -> from the login service, token says role "guest"       -> blocked
- bob   -> not in the login service; we listed him as a "member" -> allowed (fallback to our list)
- dave  -> not in the login service; we gave him no role         -> blocked

Don't worry about the key/signing plumbing below; the point is both kinds of user
get the right answer from one AgentOS.

Run it:
    pip install "agno[casbin]"
    python casbin_external_idp.py
"""

import json
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
from agno.utils.cryptography import generate_rsa_keys
from jwt.algorithms import RSAAlgorithm

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

OS_ID = "casbin-idp-os"
JWKS_PATH = "tmp/idp_jwks.json"

os.makedirs("tmp", exist_ok=True)

# Keys: one keypair simulating the external IdP, one your backend self-mints with.
# In production the IdP keypair is the IdP's; you fetch its public JWKS.
idp_private, idp_public = generate_rsa_keys()
cust_private, cust_public = generate_rsa_keys()

# Publish the IdP public key as a JWKS file (what you'd fetch from the IdP).
_jwk = json.loads(RSAAlgorithm.to_jwk(RSAAlgorithm(RSAAlgorithm.SHA256).prepare_key(idp_public)))
_jwk.update({"kid": "idp-key-1", "use": "sig", "alg": "RS256"})
with open(JWKS_PATH, "w") as f:
    json.dump({"keys": [_jwk]}, f)

# Casbin policy: a "member" may read+run the research agent. bob (a no-IdP user)
# is assigned the member role in the store. IdP users carry their role in the token.
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
with open("tmp/casbin_idp_model.conf", "w") as f:
    f.write(MODEL)
enforcer = casbin.Enforcer("tmp/casbin_idp_model.conf")
enforcer.add_policy("member", "agents/research-agent", "read")
enforcer.add_policy("member", "agents/research-agent", "run")
enforcer.add_grouping_policy("bob", "member")  # no-IdP user's role lives in the store

# Setup database
db = SqliteDb(db_file="tmp/agentos.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
)

# One AgentOS trusting BOTH token sources, authorized by Casbin.
# roles_claim="roles" -> read roles off IdP tokens; fall back to the store otherwise.
agent_os = AgentOS(
    id=OS_ID,
    description="Casbin AgentOS trusting IdP and self-minted tokens",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        algorithm="RS256",
        verification_keys=[cust_public],  # verifies self-minted (no-IdP) tokens
        jwks_file=JWKS_PATH,  # verifies external-IdP tokens
        verify_audience=True,
        audience=OS_ID,
        authorization_provider=CasbinAuthorizationProvider(enforcer, roles_claim="roles"),
    ),
)

# Get the app
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------


def idp_token(sub: str, roles: list[str]) -> str:
    """A token as an external IdP (Auth0/WorkOS) would issue: RS256 + kid + roles."""
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "roles": roles, "exp": datetime.now(UTC) + timedelta(hours=24)},
        idp_private, algorithm="RS256", headers={"kid": "idp-key-1"},
    )


def self_token(sub: str) -> str:
    """A token your own backend self-mints with your key (no IdP, no roles claim)."""
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=24)},
        cust_private, algorithm="RS256",
    )


if __name__ == "__main__":
    """
    Run this file to authorize both token sources against the same AgentOS.

    WITH IdP: roles ride the token's `roles` claim.
    WITHOUT IdP: roles come from the Casbin store (g, <sub>, role).
    The same policy ("member" can read research-agent) authorizes both, so an IdP
    member and a self-minted store member both succeed, and non-members are denied.
    """
    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)  # quiet framework logs for a clean transcript
    client = TestClient(app)

    alice = idp_token("alice@corp", ["member"])  # IdP user, member
    carol = idp_token("carol@corp", ["guest"])  # IdP user, no grant
    bob = self_token("bob")  # self-minted, member via the Casbin store
    dave = self_token("dave")  # self-minted, no role

    def show(label: str, tok: str, note: str = "") -> None:
        r = client.get("/agents/research-agent", headers={"Authorization": f"Bearer {tok}"})
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:46s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 80)
    print("A MIX: SOME USERS FROM THE LOGIN SERVICE, SOME MANAGED BY US")
    print("=" * 80)
    print("  everyone below is asking to look at the same agent.\n")
    show("alice  (login service, role on token = member)", alice, "use the token's role -> in")
    show("carol  (login service, role on token = guest)", carol, "use the token's role -> bounced")
    show("bob    (not in login service, we listed as member)", bob, "no role on token, fall back to our list -> in")
    show("dave   (not in login service, no role anywhere)", dave, "no role on token, none in our list -> bounced")
    print("=" * 80)
    print("the point: one AgentOS handles both. if the token brings a role we use it;")
    print("if not, we fall back to our own list. same agent, same protection, either way.")
    print("=" * 80)
