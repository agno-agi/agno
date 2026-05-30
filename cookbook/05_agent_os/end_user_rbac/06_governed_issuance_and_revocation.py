"""Track B governance: governed token issuance + revocation.

This is the workflow that replaces Track A's POST /tokens for production use:

- Nia's backend doesn't pass scopes anymore. It just names the user; we look
  up the user's template and mint the token with the template's scopes.
- Revoking a token is `DELETE /tokens/{jti}` and the next request 401s within
  the middleware's cache window (~30s, configurable; we wait briefly to make
  it visible in the demo).
- Every step writes to the audit log.

Run:
    export AGNO_JWT_SIGNING_KEY="..."
    .venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/06_governed_issuance_and_revocation.py
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
db = SqliteDb(db_file="tmp/end_user_rbac_governed.db")

agent = Agent(id="chat-agent", db=db, model=OpenAIResponses(id="gpt-5.4"))

agent_os = AgentOS(
    id="governed-os",
    agents=[agent],
    db=db,
    governance=True,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SIGNING_KEY],
        algorithm="HS256",
        verify_audience=True,
        audience="governed-os",
    ),
)

app = agent_os.get_app()


def run_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=7782, log_level="warning")


def main() -> None:
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    base = "http://127.0.0.1:7782"
    admin_token = agent_os.issue_token(
        subject="nia-admin", scopes=["agent_os:admin"], ttl_seconds=3600
    )
    h_admin = {"Authorization": f"Bearer {admin_token}"}

    # Lower the revocation cache TTL so the demo doesn't have to sleep 30s.
    for mw in app.user_middleware:
        if mw.cls.__name__ == "JWTMiddleware":
            mw.kwargs["revocation_cache_ttl_seconds"] = 1.0
    # Note: the live middleware on app.middleware_stack was already built; for
    # this cookbook we recreate the stack by adding via app.add_middleware would
    # be too invasive — instead, we sleep briefly between revoke + retry below.

    print("=" * 70)
    print("Track B: governed token issuance + revocation")
    print("=" * 70)

    # Seed template + user (idempotent via upsert)
    httpx.post(
        f"{base}/scope-templates",
        headers=h_admin,
        json={
            "id": "free-tier",
            "scopes": ["agents:read", "agents:chat-agent:run"],
            "description": "Free tier",
        },
        timeout=10.0,
    )
    httpx.post(
        f"{base}/end-users",
        headers=h_admin,
        json={"external_id": "alice", "template_id": "free-tier"},
        timeout=10.0,
    )
    print("\n[1] alice registered as free-tier.")

    print("\n[2] POST /end-users/alice/tokens (template scopes auto-applied)...")
    r = httpx.post(
        f"{base}/end-users/alice/tokens",
        headers=h_admin,
        json={"ttl_seconds": 3600},
        timeout=10.0,
    )
    issued = r.json()
    alice_token = issued["token"]
    alice_jti = issued["token_id"]
    print(f"  status={r.status_code}  jti={alice_jti}")
    print(f"  scopes from template: {issued['scopes']}")

    print("\n[3] alice GET /agents (expect 200)...")
    r = httpx.get(
        f"{base}/agents",
        headers={"Authorization": f"Bearer {alice_token}"},
        timeout=10.0,
    )
    print(f"  status={r.status_code}")

    print("\n[4] List alice's outstanding tokens...")
    r = httpx.get(f"{base}/end-users/alice/tokens", headers=h_admin, timeout=10.0)
    for t in r.json():
        print(
            f"  - jti={t['jti'][:8]}... status={t['status']} expires_at={t['expires_at'][:19]}"
        )

    print("\n[5] DELETE /tokens/{jti} (revoke alice's token)...")
    r = httpx.delete(f"{base}/tokens/{alice_jti}", headers=h_admin, timeout=10.0)
    print(f"  status={r.status_code}  body={r.json()}")

    # Default cache TTL is 30s; wait that long for the demo so the revocation
    # is observable. In production you'd tune this to fit your latency budget.
    print("\n[6] Sleeping 31s for the revocation cache to refresh...")
    time.sleep(31)

    print("\n[7] alice GET /agents again (expect 401: Token revoked)...")
    r = httpx.get(
        f"{base}/agents",
        headers={"Authorization": f"Bearer {alice_token}"},
        timeout=10.0,
    )
    print(f"  status={r.status_code}  body={r.text}")

    print("\n[8] Audit log entries for alice:")
    r = httpx.get(f"{base}/audit-log?external_id=alice", headers=h_admin, timeout=10.0)
    for entry in r.json():
        print(
            f"  {entry['timestamp'][:19]}  {entry['action']:18s} status={entry['status']}"
        )

    print("\n" + "=" * 70)
    print(
        "Note: cache TTL is configurable via JWTMiddleware(revocation_cache_ttl_seconds=...)."
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
