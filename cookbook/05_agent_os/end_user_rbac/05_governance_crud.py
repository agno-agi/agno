"""Track B governance: scope templates + end-user CRUD.

This is the first cookbook for Track B. It exercises the persistence layer:

1. Boots an AgentOS with governance=True.
2. Mints a bootstrap admin token (so we can call governance endpoints).
3. Creates two scope templates: `free-tier` and `pro-tier`.
4. Creates two end-users: alice (free-tier) and bob (pro-tier).
5. Lists them, fetches one by id, updates alice's metadata.
6. Soft-deletes bob and confirms his status flips to `deleted`.
7. Tries to delete the `pro-tier` template — fails because bob is still
   technically referencing it (soft-delete preserves the FK semantically).

Run:
    export AGNO_JWT_SIGNING_KEY="..."
    .venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/05_governance_crud.py
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
db = SqliteDb(db_file="tmp/end_user_rbac_governance.db")

agent = Agent(id="chat-agent", db=db, model=OpenAIResponses(id="gpt-5.4"))

agent_os = AgentOS(
    id="governance-os",
    description="AgentOS with Track B governance enabled",
    agents=[agent],
    db=db,
    governance=True,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SIGNING_KEY],
        algorithm="HS256",
        verify_audience=True,
        audience="governance-os",
    ),
)

app = agent_os.get_app()


def run_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=7781, log_level="warning")


def main() -> None:
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    base = "http://127.0.0.1:7781"

    # Bootstrap: AgentOS operator mints an admin token for the governance API.
    # In production this lives in Nia's backend env var, never exposed to end-users.
    admin_token = agent_os.issue_token(
        subject="nia-admin",
        scopes=["agent_os:admin"],
        ttl_seconds=3600,
    )
    h = {"Authorization": f"Bearer {admin_token}"}

    print("=" * 70)
    print("Track B governance: scope templates + end-user CRUD")
    print("=" * 70)

    print("\n[1] Create scope templates...")
    for tpl in [
        {
            "id": "free-tier",
            "scopes": [
                "agents:read",
                "agents:chat-agent:run",
                "sessions:read",
                "sessions:write",
            ],
            "description": "Free tier: chat with the agent, see own sessions.",
        },
        {
            "id": "pro-tier",
            "scopes": [
                "agents:read",
                "agents:chat-agent:run",
                "sessions:read",
                "sessions:write",
                "memories:read",
                "memories:write",
            ],
            "description": "Pro tier: chat + persisted memories.",
        },
    ]:
        r = httpx.post(f"{base}/scope-templates", headers=h, json=tpl, timeout=10.0)
        print(f"  POST /scope-templates id={tpl['id']} -> {r.status_code}")

    print("\n[2] List templates...")
    r = httpx.get(f"{base}/scope-templates", headers=h, timeout=10.0)
    for t in r.json():
        print(f"  - {t['id']}: {len(t['scopes'])} scopes")

    print("\n[3] Create end-users...")
    for user in [
        {
            "external_id": "alice",
            "template_id": "free-tier",
            "metadata": {"email": "alice@niapp.com"},
        },
        {
            "external_id": "bob",
            "template_id": "pro-tier",
            "metadata": {"email": "bob@niapp.com"},
        },
    ]:
        r = httpx.post(f"{base}/end-users", headers=h, json=user, timeout=10.0)
        print(f"  POST /end-users external_id={user['external_id']} -> {r.status_code}")

    print("\n[4] List end-users...")
    r = httpx.get(f"{base}/end-users", headers=h, timeout=10.0)
    for u in r.json():
        print(f"  - {u['external_id']} ({u['template_id']}, {u['status']})")

    print("\n[5] Update alice's metadata...")
    r = httpx.patch(
        f"{base}/end-users/alice",
        headers=h,
        json={"metadata": {"email": "alice@niapp.com", "tier_changed": True}},
        timeout=10.0,
    )
    print(
        f"  PATCH /end-users/alice -> {r.status_code}  metadata={r.json()['metadata']}"
    )

    print("\n[6] Soft-delete bob...")
    r = httpx.delete(f"{base}/end-users/bob", headers=h, timeout=10.0)
    print(f"  DELETE /end-users/bob -> {r.status_code}  body={r.json()}")
    r = httpx.get(f"{base}/end-users/bob", headers=h, timeout=10.0)
    print(f"  GET /end-users/bob -> status={r.json()['status']}")

    print("\n[7] Audit log so far:")
    r = httpx.get(f"{base}/audit-log", headers=h, timeout=10.0)
    for entry in r.json()[:6]:
        print(
            f"  {entry['timestamp'][:19]}  {entry['action']:24s} resource={entry['resource']}"
        )

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
