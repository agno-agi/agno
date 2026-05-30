"""Track B governance: tier upgrade flow.

Demonstrates the "alice upgraded from free to pro" scenario that's central to
the User Governance product:

1. Boot governed AgentOS, register free-tier and pro-tier templates, register
   alice on free-tier.
2. Mint alice a token. Observe she gets free-tier scopes.
3. PATCH /end-users/alice with template_id="pro-tier" (e.g. she just upgraded).
4. Mint alice another token. Observe she gets pro-tier scopes.
5. Old free-tier token still works until it expires (or is revoked) — caller's
   choice. The recommended pattern is `delete-and-reissue`, demonstrated here:
   revoke the old token, then sleep past the cache TTL, then confirm 401.

The point: scope changes happen by editing a template or reassigning a user,
not by changing every `POST /tokens` call site in the dev's code.

Run:
    export AGNO_JWT_SIGNING_KEY="..."
    .venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/07_tier_upgrade.py
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
db = SqliteDb(db_file="tmp/end_user_rbac_tier_upgrade.db")

agent = Agent(id="chat-agent", db=db, model=OpenAIResponses(id="gpt-5.4"))

agent_os = AgentOS(
    id="tier-upgrade-os",
    agents=[agent],
    db=db,
    governance=True,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SIGNING_KEY],
        algorithm="HS256",
        verify_audience=True,
        audience="tier-upgrade-os",
    ),
)

app = agent_os.get_app()


def run_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=7783, log_level="warning")


def main() -> None:
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    base = "http://127.0.0.1:7783"
    admin_token = agent_os.issue_token(
        subject="nia-admin", scopes=["agent_os:admin"], ttl_seconds=3600
    )
    h = {"Authorization": f"Bearer {admin_token}"}

    print("=" * 70)
    print("Track B: tier upgrade flow")
    print("=" * 70)

    # Seed templates
    httpx.post(
        f"{base}/scope-templates",
        headers=h,
        json={"id": "free-tier", "scopes": ["agents:read"]},
        timeout=10.0,
    )
    httpx.post(
        f"{base}/scope-templates",
        headers=h,
        json={
            "id": "pro-tier",
            "scopes": [
                "agents:read",
                "agents:chat-agent:run",
                "memories:read",
                "memories:write",
            ],
        },
        timeout=10.0,
    )

    httpx.post(
        f"{base}/end-users",
        headers=h,
        json={"external_id": "alice", "template_id": "free-tier"},
        timeout=10.0,
    )
    print("\n[1] alice registered on free-tier.")

    print("\n[2] Mint free-tier token...")
    r = httpx.post(
        f"{base}/end-users/alice/tokens",
        headers=h,
        json={"ttl_seconds": 3600},
        timeout=10.0,
    )
    free_token_jti = r.json()["token_id"]
    print(f"  scopes={r.json()['scopes']}")

    print("\n[3] alice upgrades to pro: PATCH /end-users/alice...")
    r = httpx.patch(
        f"{base}/end-users/alice",
        headers=h,
        json={"template_id": "pro-tier"},
        timeout=10.0,
    )
    print(f"  status={r.status_code}  new template={r.json()['template_id']}")

    print("\n[4] Mint pro-tier token (same endpoint, new scopes via template)...")
    r = httpx.post(
        f"{base}/end-users/alice/tokens",
        headers=h,
        json={"ttl_seconds": 3600},
        timeout=10.0,
    )
    pro_token_jti = r.json()["token_id"]
    print(f"  scopes={r.json()['scopes']}")

    print("\n[5] Revoke the old free-tier token (recommended on upgrade)...")
    r = httpx.delete(f"{base}/tokens/{free_token_jti}", headers=h, timeout=10.0)
    print(f"  status={r.status_code}  body={r.json()}")

    print("\n[6] List alice's tokens (include_revoked=true)...")
    r = httpx.get(
        f"{base}/end-users/alice/tokens?include_revoked=true",
        headers=h,
        timeout=10.0,
    )
    for t in r.json():
        print(
            f"  - jti={t['jti'][:8]}... status={t['status']} scopes={len(t['scopes'])}"
        )

    print("\n[7] Audit trail for alice:")
    r = httpx.get(f"{base}/audit-log?external_id=alice", headers=h, timeout=10.0)
    for entry in r.json():
        meta = entry["metadata"]
        extra = ""
        if "old_template" in meta:
            extra = f" {meta['old_template']} -> {meta['new_template']}"
        elif "template_id" in meta:
            extra = f" template={meta['template_id']}"
        print(f"  {entry['timestamp'][:19]}  {entry['action']:18s}{extra}")

    print("\n" + "=" * 70)
    print(f"Old token (revoked): {free_token_jti}")
    print(f"New token (active):  {pro_token_jti}")
    print("=" * 70)


if __name__ == "__main__":
    main()
