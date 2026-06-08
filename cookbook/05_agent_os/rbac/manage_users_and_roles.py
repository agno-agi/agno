"""
Run an AgentOS that serves the user + role management API (for a frontend)

(New to this? Read managed_roles.py first, then managed_users.py.)

This is the "admin backend": it starts a real AgentOS server and leaves it
running, exposing the /authz management API so a frontend (or your own admin UI)
can create roles, add users, assign roles, and disable people - live. It works
both with a control plane / login service (operators authorized by their token
scopes) and on its own (end users managed in the OS-local store) - both at once.

What it serves (all admin-only):
    GET    /authz/roles                 list roles
    PUT    /authz/roles/{role}          set what a role can do
    GET    /authz/scopes                the permission catalog (for a UI grid)
    GET    /authz/users                 list users (with their roles)
    POST   /authz/users                 add a user
    POST   /authz/users/{id}/roles      give a user a role
    POST   /authz/users/{id}/disable    revoke a user (blocked on next request)
    GET    /authz/audit                 the change trail
    GET    /authz/decisions             the access trail

It seeds a couple of roles and users so the frontend has something to show, and
makes ONE bootstrap admin (so someone can call the admin API).

Run it:
    pip install "agno[roles]"
    python manage_users_and_roles.py
Then point your frontend at http://localhost:7777 (CORS is open to the usual dev
ports). The server keeps running until you Ctrl-C.

Two authz planes run in parallel here, by default - we pass a LIST of providers
(``authorization_provider=[ScopeAuthorizationProvider(), roles.provider]``) and a
request is allowed if either grants:
  - control plane / operators: a token that already carries scopes (e.g. an
    agno-cloud / frontend token) is authorized straight from those scopes.
  - managed store / end users: everyone else is authorized against the OS-local
    role store you manage at runtime.
So a scope-bearing frontend token can connect and operate, while the store still
governs your managed users.

Verifying tokens - pick whichever fits; auto-selected by env, no code change:
  - Dev (default): a built-in HS256 secret. On startup it prints a ready-made
    admin bearer token you can paste into the frontend / curl to try the API.
  - Control plane / IdP: set ONE of
        JWT_JWKS_URL          a JWKS the control plane / IdP publishes (RS256)
        JWT_VERIFICATION_KEY  your OS public key (RS256) or an HS256 secret
    plus OS_ID (the token audience / your os_id) and, optionally,
        JWT_ISSUER           pin the issuer, e.g. "agent-os-api"

To MANAGE roles/users over /authz you must be an admin. That comes from either an
``agent_os:admin`` scope on the token, OR being seeded in the store - so set
ADMIN_SUBJECT to the `sub` of your token (decode it: the `sub` claim). e.g.
    OS_ID="<your-os-id>" JWT_VERIFICATION_KEY="<os public key>" \\
    ADMIN_SUBJECT="you@company.com" python manage_users_and_roles.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.authz.audit import DbAuditSink
from agno.os.authz.role_router import get_roles_router
from agno.os.authz.role_store import ManagedRoleStore
from agno.os.authz.scope_provider import ScopeAuthorizationProvider
from agno.os.authz.user_store import ManagedUserStore
from agno.os.config import AuthorizationConfig
from agno.os.middleware import JWTIssuer  # mint tokens your AgentOS accepts

# --- config: supports BOTH planes by default ---------------------------------
# Plane 1 - control plane / operators: tokens minted by the agno control plane
#   (or any IdP) are verified against the OS's public key or a JWKS URL; their
#   scopes authorize them (the ScopeAuthorizationProvider below).
# Plane 2 - managed store / end users: roles you manage at runtime in the store.
# Both are wired by default; you just point verification at your control plane.
OS_ID = os.getenv("OS_ID", "manage-users-os")  # the token audience (your os_id)
ADMIN_SUBJECT = os.getenv("ADMIN_SUBJECT", "admin")  # whose `sub` is the bootstrap admin
ISSUER = os.getenv("JWT_ISSUER") or None  # optionally pin the issuer (e.g. agent-os-api)

# Verification source, in priority order:
#   1. JWT_JWKS_URL         - a JWKS the control plane / IdP publishes (RS256)
#   2. JWT_VERIFICATION_KEY  - the OS public key (RS256) or an HS256 secret
#   3. dev fallback          - a built-in HS256 secret (prints an admin token)
JWKS_URL = os.getenv("JWT_JWKS_URL") or None
VERIFICATION_KEY = (os.getenv("JWT_VERIFICATION_KEY") or "").replace("\\n", "\n") or None
DEV_SECRET = "your-secret-key-at-least-256-bits-long"
if JWKS_URL:
    ALGORITHM, KEYS = "RS256", None
elif VERIFICATION_KEY:
    ALGORITHM, KEYS = ("RS256" if "BEGIN" in VERIFICATION_KEY else "HS256"), [VERIFICATION_KEY]
else:
    ALGORITHM, KEYS = "HS256", [DEV_SECRET]

# Frontends run in the browser, so the server must allow their origin.
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
]

os.makedirs("tmp", exist_ok=True)

# ONE database for everything. Pass the same `db` to AgentOS and to each store
# (db=) and they reuse its connection - agent data, roles, users, and the audit
# trail all live in the same database, no second db_url to keep in sync. (Each
# store still uses its own tables: casbin_rule, authz_users, authz_audit, ...)
db = SqliteDb(db_file="tmp/console.db")
audit = DbAuditSink(db=db)
roles = ManagedRoleStore(db=db, audit=audit)
users = ManagedUserStore(db=db, audit=audit)

# Seed roles + a couple of users so a freshly-connected frontend isn't empty.
roles.set_role_scopes("admin", ["agent_os:admin"])
roles.set_role_scopes("viewer", ["agents:*:read"])
roles.set_role_scopes("runner", ["agents:*:read", "agents:*:run"])

# The bootstrap admin (so the admin API is usable at all), plus two demo users.
if not roles.roles_of(ADMIN_SUBJECT):
    roles.assign(ADMIN_SUBJECT, "admin")
users.upsert(ADMIN_SUBJECT, name="Bootstrap admin")
users.upsert("bob", email="bob@co", name="Bob")
roles.assign("bob", "viewer")
users.upsert("carol", email="carol@co", name="Carol")
roles.assign("carol", "runner")

research_agent = Agent(id="research-agent", name="Research Agent", model=OpenAIChat(id="gpt-4o"), db=db)

agent_os = AgentOS(
    id=OS_ID,
    description="User + role management AgentOS",
    db=db,  # same database the stores use
    agents=[research_agent],
    cors_allowed_origins=CORS_ORIGINS,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=KEYS,
        jwks_url=JWKS_URL,
        algorithm=ALGORITHM,
        verify_audience=True,
        audience=OS_ID,
        issuer=ISSUER,
        # Two authz planes on one OS, in parallel - pass a LIST, allowed if any
        # grants:
        #  - ScopeAuthorizationProvider: operators whose token already carries
        #    scopes (e.g. an agno-cloud / frontend token) are authorized from it.
        #  - roles.provider: end users managed in the OS-local store.
        # (Without the scope plane, a scope-bearing frontend token gets 403
        # because the store ignores token scopes.)
        authorization_provider=[ScopeAuthorizationProvider(), roles.provider],
        user_store=users,
        audit=audit,  # record every access decision too
    ),
)
app = agent_os.get_app()
app.include_router(get_roles_router(roles, user_store=users))


if __name__ == "__main__":
    print("\n" + "=" * 78)
    print("USER + ROLE MANAGEMENT AGENTOS - serving for a frontend")
    print("=" * 78)
    src = "JWKS_URL" if JWKS_URL else ("JWT_VERIFICATION_KEY" if VERIFICATION_KEY else "dev secret")
    print("  endpoint:   http://localhost:7777")
    print("  manage at:  http://localhost:7777/authz/...   (admin-only)")
    print("  planes:     control plane (token scopes) + managed role store, in parallel")
    print(f"  verify:     {ALGORITHM} via {src}   audience={OS_ID}   admin sub={ADMIN_SUBJECT!r}")
    print(f"  CORS open to: {', '.join(CORS_ORIGINS)}")

    # Dev only (built-in HS256 secret): mint a ready-to-use admin token so you can
    # try it immediately. JWTIssuer is the mint-side helper - same claims AgentOS
    # verifies, with exp/iat/jti stamped. (Control-plane RS256 tokens are minted by
    # the control plane, not here - that key is public.)
    is_dev = ALGORITHM == "HS256" and not VERIFICATION_KEY and not JWKS_URL
    if is_dev:
        admin_token = JWTIssuer(DEV_SECRET, audience=OS_ID).create_token(ADMIN_SUBJECT, expires_in=7 * 24 * 3600)
        print("\n  dev mode - admin bearer token (paste into your frontend / curl):")
        print(f"    {admin_token}")
        print("\n  e.g.:  curl -H 'Authorization: Bearer <token>' http://localhost:7777/authz/users")
    else:
        print("\n  control-plane mode: the frontend sends a token signed by your control")
        print(f"  plane / IdP (aud={OS_ID!r}). Operators are authorized by the token's scopes;")
        print("  end users by the role store. To manage roles, the caller needs agent_os:admin")
        print(f"  on the token OR be seeded here (ADMIN_SUBJECT={ADMIN_SUBJECT!r}).")
    print("=" * 78 + "\n")

    agent_os.serve(app, host="0.0.0.0", port=7777)
