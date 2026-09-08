"""
Run an AgentOS that serves the USER management API (no roles) - for a frontend

Sibling of 06_manage_users_and_roles.py, but users ONLY: a directory (who exists +
the disabled off-switch) with NO role store. End users are authorized by their
token scopes (a control plane / IdP issues them); AgentOS just keeps the roster
and the kill-switch. Use this when roles live elsewhere and you only need AgentOS
to manage the list of people.

What it serves (admin-only):
    GET    /users            list users (search/sort/paginate)
    POST   /users            add a user
    PATCH  /users/{id}       update; {"disabled": true} revokes on next request

There is NO /authz roles API here (no role store), so a frontend renders a plain
"User Management" page with no role selector - the difference from
06_manage_users_and_roles.py.

Run it:
    pip install "agno[roles]"
    python 07_manage_users.py
Then point your frontend at http://localhost:7777 (CORS open to the dev ports).
The server keeps running until you Ctrl-C.

Verifying tokens - auto-selected by env, no code change:
  - Dev (default): a built-in HS256 secret. On startup it prints a ready-made
    admin bearer (with the agent_os:admin scope) to paste into the frontend / curl.
  - Control plane / IdP: set JWT_JWKS_FILE or JWT_VERIFICATION_KEY (+ OS_ID, and
    optionally JWT_ISSUER); operators' own tokens carry agent_os:admin.

Admin here comes from the TOKEN's agent_os:admin scope, not a seeded store row -
there is no role store to seed an admin in. That is the whole point of this file.
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, create_dev_token
from agno.os.authz.audit import DbAuditSink
from agno.os.authz.role_router import get_users_router
from agno.os.authz.user_store import ManagedUserStore
from agno.os.config import AuthorizationConfig, UserDirectoryConfig

OS_ID = os.getenv("OS_ID", "manage-users-os")  # the token audience (your os_id)
ADMIN_SUBJECT = os.getenv("ADMIN_SUBJECT", "admin@example.com")
ISSUER = os.getenv("JWT_ISSUER") or None

# Verification source, in priority order (same as the sibling):
JWKS_FILE = os.getenv("JWT_JWKS_FILE") or None
VERIFICATION_KEY = (os.getenv("JWT_VERIFICATION_KEY") or "").replace(
    "\\n", "\n"
) or None
DEV_SECRET = "your-secret-key-at-least-256-bits-long"

if JWKS_FILE:
    ALGORITHM, KEYS = "RS256", None
elif VERIFICATION_KEY:
    ALGORITHM, KEYS = (
        ("RS256" if "BEGIN" in VERIFICATION_KEY else "HS256"),
        [VERIFICATION_KEY],
    )
else:
    ALGORITHM, KEYS = "HS256", [DEV_SECRET]

CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "null",
]

os.makedirs("tmp", exist_ok=True)

# One database, one store: the user directory. No role store - this is the users-only setup.
db = SqliteDb(db_file="tmp/manage_users.db")
audit = DbAuditSink(db=db)
users = ManagedUserStore(db=db, audit=audit)

# Seed a couple of people so a freshly-connected frontend isn't empty.
users.upsert(ADMIN_SUBJECT, name="Bootstrap admin")
users.upsert("bob", email="bob@co", name="Bob")
users.upsert("carol", email="carol@co", name="Carol")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

# authorization=True on the DEFAULT scope plane: no role store and no provider, so the built-in
# ScopeAuthorizationProvider (token scopes) governs. The directory tracks who people are and backs
# the disabled kill-switch; roles, if any, live in your control plane. Admin of /users is the
# agent_os:admin scope on the caller's token.
agent_os = AgentOS(
    id=OS_ID,
    description="User management AgentOS (no roles)",
    db=db,
    agents=[research_agent],
    cors_allowed_origins=CORS_ORIGINS,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=KEYS,
        jwks_file=JWKS_FILE,
        algorithm=ALGORITHM,
        verify_audience=True,
        audience=OS_ID,
        issuer=ISSUER,
        audit=audit,  # record every access decision
    ),
    # The user directory: who exists + the disabled off-switch. A peer of authorization.
    user_directory=UserDirectoryConfig(store=users),
)
app = agent_os.get_app()
# Mount ONLY the user directory API - no get_roles_router, so there is no /authz roles surface for
# a frontend to render. This is the difference from 06_manage_users_and_roles.py.
app.include_router(get_users_router(users))


if __name__ == "__main__":
    print("\n" + "=" * 78)
    print("USER MANAGEMENT AGENTOS (no roles) - serving for a frontend")
    print("=" * 78)
    src = (
        "JWKS_FILE"
        if JWKS_FILE
        else ("JWT_VERIFICATION_KEY" if VERIFICATION_KEY else "dev secret")
    )
    print("  endpoint:   http://localhost:7777")
    print("  manage at:  http://localhost:7777/users   (admin-only)")
    print("  plane:      scope RBAC (token scopes) + a user directory, no role store")
    print(
        f"  verify:     {ALGORITHM} via {src}   audience={OS_ID}   admin sub={ADMIN_SUBJECT!r}"
    )
    print(f"  CORS open to: {', '.join(CORS_ORIGINS)}")

    is_dev = ALGORITHM == "HS256" and KEYS == [DEV_SECRET]
    if is_dev:
        # No role store to seed an admin in, so admin is the token's agent_os:admin scope. Mint one
        # (from the source-visible DEV_SECRET) so you can call /users immediately.
        admin_token = create_dev_token(
            ADMIN_SUBJECT,
            secret=DEV_SECRET,
            scopes=["agent_os:admin"],
            audience=OS_ID,
            expires_in=7 * 24 * 3600,
        )
        print(
            "\n  dev mode - admin bearer token (agent_os:admin scope; paste into your frontend / curl):"
        )
        print(f"    {admin_token}")
        print(
            "\n  try:  curl -H 'Authorization: Bearer <token>' http://localhost:7777/users"
        )
    else:
        print(
            "\n  control-plane mode: operators' own tokens carry agent_os:admin (aud must match OS_ID)."
        )
    print("=" * 78 + "\n")

    # Bind to localhost by default: in dev the admin token is minted from the source-visible
    # DEV_SECRET, so serving on 0.0.0.0 would let anyone on the network forge one. Set HOST=0.0.0.0
    # only when verifying against a real control-plane key / JWKS.
    agent_os.serve(app, host=os.getenv("HOST", "127.0.0.1"), port=7777)
