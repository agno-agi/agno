"""
Casbin with External IdP and Self-Minted Tokens Example with AgentOS

This example demonstrates one AgentOS serving BOTH user populations, because the
authorization layer only ever sees a `sub`. Only token minting/verification differs:
- Users WITH an external IdP (Auth0/WorkOS/Clerk): the IdP signs the token; AgentOS
  verifies it against the IdP's published keys (a JWKS); roles come FROM the token.
- Users WITHOUT an IdP: your backend self-mints a token with your own key (here a
  plain jwt.encode); AgentOS verifies it against that key; roles come FROM the Casbin store.

A single AgentOS trusts both at once via `jwks_file` (the IdP's keys) AND
`verification_keys` (your self-mint key). The same Casbin policy authorizes both.

Prerequisites:
- pip install "agno[casbin]"
- Set OPENAI_API_KEY to actually run an agent (authorization is enforced regardless)
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
        verdict = "DENIED " if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:42s} -> {r.status_code} {verdict}  {note}")

    print("\n" + "=" * 70)
    print("IdP + self-minted tokens — running the scenario for you")
    print("(every line hits GET /agents/research-agent on the SAME AgentOS)")
    print("=" * 70)
    show("alice@corp  IdP token,   roles=[member]", alice, "IdP member -> allowed")
    show("carol@corp  IdP token,   roles=[guest]", carol, "IdP guest -> blocked")
    show("bob         self-minted, store member", bob, "store member -> allowed")
    show("dave        self-minted, no role", dave, "no role -> blocked")
    print("=" * 70)
