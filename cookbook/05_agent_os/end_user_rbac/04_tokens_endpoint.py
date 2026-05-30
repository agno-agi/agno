"""End-user RBAC: SaaS flow via POST /tokens.

This is the flow that lets a developer use AgentOS without holding the signing
key themselves. AgentOS exposes POST /tokens; the developer's backend calls
that endpoint (using its own bootstrap token with the `tokens:issue` scope) to
mint scoped tokens for end-users.

Flow:
1. AgentOS starts up with HS256 authorization.
2. We mint a *bootstrap* token (subject="nia-backend") with `tokens:issue`.
   In production, this token lives in Nia's backend env var, the same way an
   API key would. It is NEVER given to end-users.
3. Nia's backend uses the bootstrap token to call POST /tokens, requesting a
   token for end-user "alice" with the scopes she should have.
4. Nia's backend hands alice's token to alice's browser. Alice's browser then
   hits the agent endpoints directly.
5. We verify alice's token can list agents (200) and cannot delete (403).
6. We also verify the guardrail: trying to mint a token that itself carries
   `tokens:issue` is refused with 400.

Run:
    export AGNO_JWT_SIGNING_KEY="..."
    .venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/04_tokens_endpoint.py
"""

import os
import threading
import time

import httpx
import uvicorn
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

SIGNING_KEY = os.getenv("AGNO_JWT_SIGNING_KEY")
if not SIGNING_KEY:
    raise SystemExit("Set AGNO_JWT_SIGNING_KEY before running this example.")

os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/end_user_rbac_tokens_endpoint.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
)

agent_os = AgentOS(
    id="saas-os",
    description="AgentOS demonstrating SaaS-style token issuance via POST /tokens",
    agents=[research_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SIGNING_KEY],
        algorithm="HS256",
        verify_audience=True,
        audience="saas-os",
    ),
)

app = agent_os.get_app()


def run_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=7780, log_level="warning")


def main() -> None:
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    base = "http://127.0.0.1:7780"

    # Step 1: AgentOS operator hands Nia's backend a bootstrap token with
    # tokens:issue. This is done out-of-band (e.g. one-time admin action),
    # NOT through the /tokens API. The bootstrap token never reaches an
    # end-user.
    nia_backend_token = agent_os.issue_token(
        subject="nia-backend",
        scopes=["tokens:issue"],
        ttl_seconds=86400,
    )

    print("=" * 70)
    print("End-user RBAC: SaaS flow via POST /tokens")
    print("=" * 70)
    print(
        f"\nBootstrap token for Nia's backend (kept in their env var):\n  {nia_backend_token[:40]}..."
    )

    # Step 2: Nia's backend asks AgentOS to mint a token for end-user alice.
    print("\n[Nia backend] POST /tokens to mint a token for alice...")
    r = httpx.post(
        f"{base}/tokens",
        headers={"Authorization": f"Bearer {nia_backend_token}"},
        json={
            "subject": "alice",
            "scopes": ["agents:read", "agents:research-agent:run"],
            "ttl_seconds": 3600,
        },
        timeout=10.0,
    )
    print(f"  status={r.status_code}")
    if r.status_code != 200:
        print(f"  body={r.text}")
        raise SystemExit("Token issuance failed.")
    issued = r.json()
    alice_token = issued["token"]
    print(
        f"  jti={issued['token_id']}  audience={issued['audience']}  expires_in={issued['expires_in']}s"
    )

    # Step 3: Alice's browser uses the token. She can list agents.
    print("\n[alice] GET /agents (expect 200)...")
    r = httpx.get(
        f"{base}/agents",
        headers={"Authorization": f"Bearer {alice_token}"},
        timeout=10.0,
    )
    print(f"  status={r.status_code}")

    # Step 4: She cannot delete (no agents:delete scope) — expect 403.
    print("\n[alice] DELETE /agents/research-agent (expect 403)...")
    r = httpx.delete(
        f"{base}/agents/research-agent",
        headers={"Authorization": f"Bearer {alice_token}"},
        timeout=10.0,
    )
    print(f"  status={r.status_code}")

    # Step 5: She also cannot mint more tokens, even though we never restricted
    # the /tokens endpoint per-subject. Default scope mappings already require
    # tokens:issue, and alice's token does not have it.
    print("\n[alice] POST /tokens (expect 403 — alice lacks tokens:issue)...")
    r = httpx.post(
        f"{base}/tokens",
        headers={"Authorization": f"Bearer {alice_token}"},
        json={
            "subject": "evil-mallory",
            "scopes": ["agent_os:admin"],
            "ttl_seconds": 60,
        },
        timeout=10.0,
    )
    print(f"  status={r.status_code}")

    # Step 6: Guardrail check — even Nia's backend cannot ask /tokens to mint a
    # token carrying tokens:issue itself (privilege-escalation footgun).
    print("\n[Nia backend] POST /tokens with scopes=[tokens:issue] (expect 400)...")
    r = httpx.post(
        f"{base}/tokens",
        headers={"Authorization": f"Bearer {nia_backend_token}"},
        json={
            "subject": "another-service",
            "scopes": ["tokens:issue"],
            "ttl_seconds": 60,
        },
        timeout=10.0,
    )
    print(f"  status={r.status_code}  body={r.text}")

    print("\n" + "=" * 70)
    print("Bootstrap token issued via Python helper, end-user tokens via HTTP.")
    print("In Track B, /end-users/{id}/tokens replaces direct scope input with")
    print("persisted scope templates and adds revocation + audit log.")
    print("=" * 70)


if __name__ == "__main__":
    main()
