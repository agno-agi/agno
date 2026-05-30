"""End-user RBAC: issue and verify a scoped token.

This is the first example in the end-user RBAC track. It demonstrates the
"developer mints a token for an end-user" flow that AgentOS streamlines via
the new AgentOS.issue_token() helper.

What it does:
1. Boots an AgentOS with HS256 JWT authorization enabled.
2. Mints a token for end-user "alice" with the scope agents:read.
3. Mints an admin token (agent_os:admin) for comparison.
4. Prints curl commands so you can verify:
   - alice can GET /agents (has agents:read)
   - alice cannot POST /agents/.../runs (lacks agents:run) -> 403
   - admin can do both

Setup:
    export AGNO_JWT_SIGNING_KEY="a-long-random-string-at-least-32-chars-please"
    .venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/01_basic_issue_and_verify.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

SIGNING_KEY = os.getenv("AGNO_JWT_SIGNING_KEY")
if not SIGNING_KEY:
    raise SystemExit(
        "Set AGNO_JWT_SIGNING_KEY before running this example. "
        "It must be the same value AgentOS uses to verify incoming tokens."
    )

db = SqliteDb(db_file="tmp/end_user_rbac.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    id="end-user-rbac-os",
    description="AgentOS with end-user token issuance",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SIGNING_KEY],
        algorithm="HS256",
        verify_audience=True,
        audience="end-user-rbac-os",
        user_isolation=True,
    ),
)

app = agent_os.get_app()


if __name__ == "__main__":
    alice_token = agent_os.issue_token(
        subject="alice",
        scopes=[
            "agents:read",
            "agents:research-agent:run",
            "sessions:read",
            "sessions:write",
        ],
        ttl_seconds=3600,
    )

    admin_token = agent_os.issue_token(
        subject="admin-1",
        scopes=["agent_os:admin"],
        ttl_seconds=3600,
    )

    print("=" * 70)
    print("End-user RBAC: scoped tokens issued for this AgentOS")
    print("=" * 70)
    print("\nAlice (agents:read + run research-agent + own sessions):")
    print(alice_token)
    print("\nAdmin (full access):")
    print(admin_token)
    print("\nTest commands:")
    print("\n# Alice can list agents:")
    print(f'curl -H "Authorization: Bearer {alice_token}" http://localhost:7777/agents')
    print("\n# Alice can run the research agent:")
    print(
        f'curl -X POST -H "Authorization: Bearer {alice_token}" '
        '-F "message=hi" http://localhost:7777/agents/research-agent/runs'
    )
    print("\n# Alice CANNOT delete the agent (no agents:delete scope) -> 403:")
    print(
        f'curl -X DELETE -H "Authorization: Bearer {alice_token}" '
        "http://localhost:7777/agents/research-agent"
    )
    print("\n# Admin can do anything:")
    print(
        f'curl -H "Authorization: Bearer {admin_token}" http://localhost:7777/sessions'
    )
    print("=" * 70)

    agent_os.serve(app="01_basic_issue_and_verify:app", port=7777, reload=True)
