"""
This example demonstrates service accounts: machine identities for AgentOS.

Coding agents and chat apps connecting to your AgentOS need long-lived credentials.
Humans get JWTs; machines get service accounts - opaque `agno_pat_...` tokens
following the GitHub PAT model. Only the SHA-256 hash is stored in the AgentOS
database, and the plaintext is returned exactly once at creation.

Successful verifications are cached in-process for a short TTL (default 30s), so PAT
auth does not hit the database on every request. Revocation takes effect within that
TTL across workers - immediately on the worker that processes the revoke. Set
`AgnoAPISettings(service_account_cache_ttl_seconds=0)` for strict instant revocation.

Runs executed with a service account attribute to it: sessions and traces created
through a `claude-code` token show `sa:claude-code` as the user.

Flow demonstrated here:
1. An admin (JWT with the admin scope) mints a token for `claude-code`
2. The machine calls the run endpoint with its `agno_pat_...` token
3. The admin lists and revokes tokens; the revoking worker rejects the token at once
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT Secret (use environment variable in production)
JWT_SECRET = "a-string-secret-at-least-256-bits-long"

# Setup database. Service accounts are stored here, next to sessions and memories.
db = SqliteDb(db_file="tmp/service_accounts_demo.db")

# Create agent
assistant_agent = Agent(
    id="assistant-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="You are a helpful assistant.",
)

agent_os = AgentOS(
    description="AgentOS with service accounts",
    agents=[assistant_agent],
    db=db,
)

# Get the final app
app = agent_os.get_app()

# Add JWT middleware with authorization enabled. Human callers authenticate with
# JWTs; bearer tokens starting with `agno_pat_` authenticate as service accounts
# against the database. Service account scopes are enforced on every request.
app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    authorization=True,
)

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Admin JWT, representing a human operator. In production the control plane
    # mints these; here we sign one locally.
    payload = {
        "sub": "demo-admin",
        "scopes": ["agent_os:admin"],
        "exp": datetime.now(UTC) + timedelta(hours=24),
        "iat": datetime.now(UTC),
    }
    admin_token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    print("Admin JWT (human operator):")
    print(admin_token)
    print()
    print("1. Mint a token for the claude-code machine identity:")
    print(
        f'   curl -X POST http://localhost:7777/service-accounts -H "Authorization: Bearer {admin_token}"',
        end="",
    )
    print(" -H 'Content-Type: application/json' -d '{\"name\": \"claude-code\"}'")
    print()
    print("   The response contains the plaintext token (agno_pat_...) exactly once.")
    print("   Default scopes: agents:run, teams:run, workflows:run, sessions:read.")
    print("   Default expiry: 90 days. Write/delete/admin scopes require")
    print("   allow_privileged_scopes=true and must be held by the minter.")
    print()
    print(
        "2. Run the agent as the machine (replace agno_pat_... with the minted token):"
    )
    print("   curl -X POST http://localhost:7777/agents/assistant-agent/runs \\")
    print(
        '        -H "Authorization: Bearer agno_pat_..." -F "message=hello" -F "stream=false"'
    )
    print()
    print("   The run's session shows sa:claude-code as the user.")
    print()
    print("3. List and revoke tokens (admin JWT again):")
    print(
        f'   curl http://localhost:7777/service-accounts -H "Authorization: Bearer {admin_token}"'
    )
    print(
        f'   curl -X DELETE http://localhost:7777/service-accounts/<id> -H "Authorization: Bearer {admin_token}"'
    )
    print()
    agent_os.serve(app="agent_os_with_service_accounts:app", port=7777)
