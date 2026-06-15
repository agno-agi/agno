"""
Using AgentOS with a login service (WorkOS / Auth0 / Okta) - you only enforce

(New to this? Read managed_roles.py first.)

When a company already has a login service, that service logs people in and puts
each person's role on their token. You don't store any users or who-has-which-role
- that's the login service's job. You keep one small thing: what each role is
allowed to do, and you enforce it on every request.

This file shows the realistic, production-shaped version of that:

1. The token is signed by the login service with its private key (RS256). You
   verify it against the service's PUBLIC keys, which it publishes as a "JWKS"
   (e.g. at https://<tenant>.auth0.com/.well-known/jwks.json). Download it and
   point agno at the file:
       AuthorizationConfig(jwks_file="auth0_jwks.json", ...)
   (Here we generate a throwaway key and publish it to a local file so the example
   runs offline; the behaviour is identical.)
2. The token says who issued it (`iss`) and who it's for (`aud`). We pin both, so
   a token meant for a different app can't be replayed against this one.
3. The person's role rides the token in a claim. WorkOS uses a single string;
   Auth0 uses a list. You write a tiny AuthorizationProvider that turns those role
   names into permissions. That provider is the whole integration - about 30 lines
   below - and it's where you'd plug in any logic you like.

The split to remember: the login service owns WHO is a "member" or "admin"; you
own WHAT those words are allowed to do.

Run it:
    pip install agno
    python idp_workos_auth0.py
(no extra services, no database, no OpenAI key - we only check who is allowed.)
"""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Set

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
from agno.os.config import AuthorizationConfig
from agno.os.scopes import get_accessible_resource_ids, has_required_scopes
from agno.utils.cryptography import generate_rsa_keys
from jwt.algorithms import RSAAlgorithm

OS_ID = "acme-agentos"  # the token "aud" - who the token is for
ISSUER = "https://acme.example-idp.com/"  # the token "iss" - who minted it
JWKS_PATH = "tmp/idp_jwks.json"
os.makedirs("tmp", exist_ok=True)


# ---------------------------------------------------------------------------
# The integration: map the login service's role names -> what they can do.
# ---------------------------------------------------------------------------

# What each role is allowed to do, in agno's permission terms ("scopes"):
#   "agents:*:read"               -> look at any agent
#   "agents:research-agent:run"   -> run the one agent called research-agent
#   "agent_os:admin"              -> do anything
# The login service decides who has each role; this dict decides what they mean.
ROLE_PERMISSIONS = {
    "member": ["agents:*:read", "agents:research-agent:run"],
    "admin": ["agent_os:admin"],
}


class RoleClaimAuthorizationProvider(AuthorizationProvider):
    """Turns the role names on the token into AgentOS permissions.

    This is the entire login-service integration. agno hands you a context with
    the decoded token claims; you decide what the caller may do. Here we look up
    the caller's role(s) on the token and expand them into agno scopes, then let
    agno's scope matcher answer the question. Swap the body for anything you like
    (call your own service, read attributes, etc.) - the rest of AgentOS doesn't
    change.
    """

    def __init__(self, role_permissions, roles_claim="roles", admin_scope="agent_os:admin"):
        self.role_permissions = role_permissions
        self.roles_claim = roles_claim  # the claim your IdP puts roles in
        self.admin_scope = admin_scope

    def _scopes_for(self, ctx: AuthorizationContext):
        """The permissions this caller has, from the role(s) on their token."""
        roles = ctx.claims.get(self.roles_claim) or []
        if isinstance(roles, str):  # WorkOS sends one string; Auth0 sends a list
            roles = [roles]
        scopes = []
        for role in roles:
            scopes.extend(self.role_permissions.get(role, []))
        return scopes

    def check(self, ctx: AuthorizationContext) -> bool:
        # Per-resource question, e.g. "may they run agent X?"
        if not ctx.resource_type or not ctx.action:
            return True
        return has_required_scopes(
            self._scopes_for(ctx),
            [f"{ctx.resource_type}:{ctx.action}"],
            resource_type=ctx.resource_type,
            resource_id=ctx.resource_id,
            admin_scope=self.admin_scope,
        )

    def authorize_route(self, ctx: AuthorizationContext, required_scopes) -> bool:
        # Route-level gate the middleware runs before the request reaches a handler.
        if not required_scopes:
            return True
        return has_required_scopes(
            self._scopes_for(ctx),
            required_scopes,
            resource_type=ctx.resource_type,
            resource_id=ctx.resource_id,
            admin_scope=self.admin_scope,
        )

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> Set[str]:
        # For list endpoints: which ids may they see ({"*"} = all).
        if not ctx.resource_type:
            return set()
        return get_accessible_resource_ids(
            self._scopes_for(ctx),
            ctx.resource_type,
            admin_scope=self.admin_scope,
            action=ctx.action,
        )


# ---------------------------------------------------------------------------
# Stand in for the login service: an RS256 keypair whose public half is published
# as a JWKS (exactly what you'd FETCH from WorkOS/Auth0). You never have this
# private key in real life - the login service holds it and signs tokens with it.
# ---------------------------------------------------------------------------

idp_private, idp_public = generate_rsa_keys()
_jwk = json.loads(RSAAlgorithm.to_jwk(RSAAlgorithm(RSAAlgorithm.SHA256).prepare_key(idp_public)))
_jwk.update({"kid": "idp-key-1", "use": "sig", "alg": "RS256"})
with open(JWKS_PATH, "w") as f:
    json.dump({"keys": [_jwk]}, f)

db = SqliteDb(db_file="tmp/agentos.db")
research_agent = Agent(id="research-agent", name="Research Agent", model=OpenAIChat(id="gpt-4o"), db=db)

agent_os = AgentOS(
    id=OS_ID,
    description="Enforce-only AgentOS behind a login service",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        # Verify tokens against the login service's published public keys
        # (in production, its JWKS downloaded from .well-known/jwks.json).
        jwks_file=JWKS_PATH,
        algorithm="RS256",
        verify_audience=True,
        audience=OS_ID,  # the token must be for THIS app
        issuer=ISSUER,  # ...and minted by the login service we trust
        # The integration: roles ride the token in the "roles" claim.
        authorization_provider=RoleClaimAuthorizationProvider(ROLE_PERMISSIONS, roles_claim="roles"),
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

    def idp_token(sub, roles=None, *, key=idp_private, iss=ISSUER, aud=OS_ID):
        """A token as the login service would mint it: signed with its key, with
        the person's role(s) in the 'roles' claim."""
        claims = {"sub": sub, "aud": aud, "iss": iss, "exp": datetime.now(UTC) + timedelta(hours=8)}
        if roles is not None:
            claims["roles"] = roles
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "idp-key-1"})

    def show(label, tok, method, path, note=""):
        r = client.request(method, path, headers={"Authorization": f"Bearer {tok}"}, data={"message": "hi"})
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:52s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 84)
    print("LOGIN SERVICE OWNS IDENTITY + ROLES - WE ONLY ENFORCE")
    print("=" * 84)
    print("  the login service signs the token and stamps the role. we verify it and")
    print("  decide what that role may do. no users or assignments stored on our side.\n")

    # Auth0-style: roles is a list. WorkOS-style: roles is a single string. Both
    # work through the same provider (it normalises a string to a list).
    show("alice (roles=['member']) RUN the agent", idp_token("alice", ["member"]), "POST", "/agents/research-agent/runs", "member can run")
    show("bob   (roles='member')   LOOK at agent", idp_token("bob", "member"), "GET", "/agents/research-agent", "single-string role also works")
    show("carol (roles=['guest'])  LOOK at agent", idp_token("carol", ["guest"]), "GET", "/agents/research-agent", "guest maps to nothing -> bounced")
    show("dave  (no roles claim)   LOOK at agent", idp_token("dave"), "GET", "/agents/research-agent", "no role -> bounced")
    show("root  (roles=['admin'])  RUN the agent", idp_token("root", ["admin"]), "POST", "/agents/research-agent/runs", "admin can do anything")

    print("\n  the token plumbing is enforced too (not just the role):\n")
    # A token signed by some OTHER key (an attacker who doesn't have the IdP key).
    attacker_priv, _ = generate_rsa_keys()
    show("mallory (token signed by a DIFFERENT key)", idp_token("mallory", ["admin"], key=attacker_priv), "GET", "/agents/research-agent", "signature doesn't match the JWKS -> rejected")
    # A real-looking token but minted for a different issuer.
    show("eve (valid role but wrong issuer)", idp_token("eve", ["admin"], iss="https://evil.example/"), "GET", "/agents/research-agent", "issuer not trusted -> rejected")

    print("=" * 84)
    print("the point: the login service owns WHO has a role; the ~30-line provider owns")
    print("WHAT a role can do. tokens are verified against the service's published keys,")
    print("and pinned to the right issuer + audience. nothing about users is stored here.")
    print("=" * 84)
