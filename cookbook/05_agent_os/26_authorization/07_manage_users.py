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
    pip install "agno[os]"
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
from agno.os.authz import Authorization, UserDirectory, UserStore

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

# One database, users-only. No define_role, so there is no role store and no /authz: the default
# scope plane (the caller's token scopes) governs. The directory is the top-level user_directory
# switch on AgentOS below, so only /users is mounted.
db = SqliteDb(db_file="tmp/manage_users.db")

# The directory (roster) is seeded on the store directly so a freshly-connected frontend isn't empty.
# No roles here -- admin of /users is the agent_os:admin scope on the caller's token, not a seeded role.
users = UserStore(db=db)
users.upsert(ADMIN_SUBJECT, name="Bootstrap admin")
users.upsert("bob", email="bob@co", name="Bob")
users.upsert("carol", email="carol@co", name="Carol")

# Authorization here is verify-only (no roles). It never touches the directory.
authz = Authorization(
    db=db,
    verification_keys=KEYS,
    jwks_file=JWKS_FILE,
    algorithm=ALGORITHM,
    verify_audience=True,
    audience=OS_ID,
    issuer=ISSUER,
    audit=True,  # record every access decision
)

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

agent_os = AgentOS(
    id=OS_ID,
    description="User management AgentOS (no roles)",
    db=db,
    agents=[research_agent],
    cors_allowed_origins=CORS_ORIGINS,
    # the directory is a top-level switch; pass the store you seeded above
    user_directory=UserDirectory(user_store=users, auto_provision=True),
    authorization=authz,  # verify-only (no roles) -> mounts /users, no /authz surface
)
app = agent_os.get_app()
# Only /users is mounted (no roles were defined), so there is no /authz roles surface for a frontend
# to render. That is the difference from 06_manage_users_and_roles.py.


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
