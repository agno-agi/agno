"""
Run an AgentOS on the legacy AuthorizationConfig and connect a frontend to it

(New to this? Read 00_quickstart_authorization.py first - it shows the current way.)

Before the Authorization object existed, you turned auth on with a switch and a
low-level config:

    AgentOS(authorization=True, authorization_config=AuthorizationConfig(...))

That spelling is deprecated but still boots, so a deployment written against it keeps
running after an upgrade. This cookbook starts a real AgentOS server on it and leaves
it running, so you can connect the AgentOS frontend (https://os.agno.com) or your own
UI and confirm the old setup still works end to end.

What the legacy config does:
- verifies the token (verification_keys / jwks_file, algorithm, audience)
- authorizes every request from the SCOPES the token carries - there is no role store,
  so nothing is looked up in a database and no /authz admin API is mounted
- user_isolation=True on the config still turns per-user data isolation on

Migrating is moving the same fields onto the Authorization object (user_isolation
becomes the top-level AgentOS switch); the behaviour is identical until you define roles:

    AgentOS(user_isolation=True, authorization=Authorization(verification_keys=..., ...))

See 00_quickstart_authorization.py for that spelling.

Run it:
    pip install "agno[os]"
    export OPENAI_API_KEY=...   # the frontend chats with the agent for real
    python 12_legacy_authorization_config.py
The server keeps running until you Ctrl-C.

Verifying tokens - pick whichever fits; auto-selected by env, no code change:
  - Control plane / frontend: set
        OS_ID                 your os_id (the token audience)
        JWT_VERIFICATION_KEY  the OS public key from the control plane (RS256)
    then add http://localhost:7777 as an OS in the frontend. Its tokens carry the
    scopes that authorize each request. e.g.
        OS_ID="<your-os-id>" JWT_VERIFICATION_KEY="<os public key>" \\
        python 12_legacy_authorization_config.py
  - Dev (default, nothing set): a built-in HS256 secret. On startup it prints a
    ready-made admin bearer token you can paste into curl or your own UI.
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

OS_ID = os.getenv("OS_ID", "legacy-authz-config-os")  # the token audience (your os_id)

# Verification source, in priority order:
#   1. JWT_VERIFICATION_KEY - the OS public key (RS256) or an HS256 secret
#   2. dev fallback         - a built-in HS256 secret (prints an admin token)
DEV_SECRET = "your-secret-key-at-least-256-bits-long"
VERIFICATION_KEY = (os.getenv("JWT_VERIFICATION_KEY") or "").replace(
    "\\n", "\n"
) or None
IS_DEV = VERIFICATION_KEY is None
ALGORITHM = "RS256" if VERIFICATION_KEY and "BEGIN" in VERIFICATION_KEY else "HS256"

# Frontends run in the browser, so the server must allow their origin. Passing a list REPLACES
# the default Agno origins, so the hosted frontend is listed here next to the local dev ports.
CORS_ORIGINS = [
    "https://os.agno.com",
    "https://os-stg.agno.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
]

os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/legacy_authz_config.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# The legacy shape: the switch plus the low-level config. Only the released fields exist here.
legacy_config = AuthorizationConfig(
    verification_keys=[VERIFICATION_KEY or DEV_SECRET],
    algorithm=ALGORITHM,
    verify_audience=True,
    audience=OS_ID,
    user_isolation=True,  # legacy spelling; AgentOS(user_isolation=True) is the current one
)

# Booting this logs a deprecation warning pointing at Authorization(...). It still works.
agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS on the legacy AuthorizationConfig",
    db=db,
    agents=[research_agent],
    cors_allowed_origins=CORS_ORIGINS,
    authorization=True,
    authorization_config=legacy_config,
)
app = agent_os.get_app()


if __name__ == "__main__":
    print("\n" + "=" * 78)
    print("LEGACY AuthorizationConfig AGENTOS - serving for a frontend")
    print("=" * 78)
    src = "dev secret" if IS_DEV else "JWT_VERIFICATION_KEY"
    print("  endpoint:   http://localhost:7777")
    print(f"  verify:     {ALGORITHM} via {src}   audience={OS_ID}")
    print("  authorize:  from the scopes on the token (no role store, no /authz)")

    if IS_DEV:
        # Dev only (built-in HS256 secret): mint a ready-to-use admin token so you can try it
        # immediately. Control-plane RS256 tokens are minted by the control plane, not here.
        now = datetime.now(UTC)
        admin_token = jwt.encode(
            {
                "sub": "admin@example.com",
                "aud": OS_ID,
                "iat": now,
                "exp": now + timedelta(days=7),
                "scopes": ["agent_os:admin"],
            },
            DEV_SECRET,
            algorithm="HS256",
        )
        print("\n  dev mode - admin bearer token (paste into your frontend / curl):")
        print(f"    {admin_token}")
        print(
            "\n  try it:  curl -H 'Authorization: Bearer <token>' http://localhost:7777/agents"
        )
    else:
        print(
            "\n  control-plane mode: add http://localhost:7777 as an OS in the frontend. It sends"
        )
        print(
            f"  a token signed by your control plane (aud={OS_ID!r}); the token's scopes decide"
        )
        print("  what the caller may do.")
    print("=" * 78 + "\n")

    # Bind to localhost by default. In dev mode the admin token is signed with the
    # source-visible DEV_SECRET, so serving on 0.0.0.0 would let anyone on the network forge
    # one. Set HOST=0.0.0.0 explicitly ONLY once you verify against a real control-plane key.
    agent_os.serve(app, host=os.getenv("HOST", "127.0.0.1"), port=7777)
