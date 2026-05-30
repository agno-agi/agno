"""Track B governance: Nia onboarding, end to end.

The demo script you'd run when showing a prospect what their integration
actually looks like. Plays the full "Nia signs up, registers tiers,
onboards users, those users chat with the agent, an admin upgrades + audits"
journey in one file.

Sections:
  A) Operator hands Nia a bootstrap token (one-time)
  B) Nia defines their tier templates (one-time, on integration day)
  C) Nia onboards three customers as they sign up
  D) Each customer logs in, gets a token, chats with the agent
  E) Admin upgrades one customer's tier
  F) Admin reviews the audit log and confirms data isolation

Run:
    export AGNO_JWT_SIGNING_KEY="..."
    export OPENAI_API_KEY="..."
    .venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/08_nia_onboarding_e2e.py
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
db = SqliteDb(db_file="tmp/end_user_rbac_nia.db")

agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    add_history_to_context=True,
)

agent_os = AgentOS(
    id="nia-os",
    description="Nia's AgentOS",
    agents=[agent],
    db=db,
    governance=True,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SIGNING_KEY],
        algorithm="HS256",
        verify_audience=True,
        audience="nia-os",
        user_isolation=True,  # per-customer data isolation
    ),
)

app = agent_os.get_app()


def run_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=7784, log_level="warning")


def main() -> None:
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    base = "http://127.0.0.1:7784"

    print("=" * 70)
    print("Nia onboarding — end to end")
    print("=" * 70)

    # ---------- A) Operator hands Nia a bootstrap token (one-time) ----------
    print("\n[A] Operator mints bootstrap admin token for Nia's backend.")
    print("    In production, this is a one-time admin action — Nia stores it in")
    print("    an env var alongside their other API keys.")
    nia_backend = agent_os.issue_token(
        subject="nia-backend",
        scopes=[
            "templates:read",
            "templates:write",
            "users:read",
            "users:write",
            "users:delete",
            "tokens:issue",
            "tokens:read",
            "tokens:revoke",
            "audit:read",
        ],
        ttl_seconds=86400,
    )
    H = {"Authorization": f"Bearer {nia_backend}"}

    # ---------- B) Nia registers their tiers ----------
    print("\n[B] Nia registers their tier templates.")
    for tier in [
        {
            "id": "free-tier",
            "scopes": [
                "agents:read",
                "agents:research-agent:run",
                "sessions:read",
                "sessions:write",
            ],
        },
        {
            "id": "pro-tier",
            "scopes": [
                "agents:read",
                "agents:research-agent:run",
                "sessions:read",
                "sessions:write",
                "memories:read",
                "memories:write",
            ],
        },
    ]:
        httpx.post(f"{base}/scope-templates", headers=H, json=tier, timeout=10.0)
        print(f"    template {tier['id']}: {len(tier['scopes'])} scopes")

    # ---------- C) Nia onboards three customers ----------
    print("\n[C] Three customers sign up on Nia's product.")
    customers = [
        ("alice", "free-tier"),
        ("bob", "free-tier"),
        ("carol", "pro-tier"),
    ]
    for external_id, tier in customers:
        httpx.post(
            f"{base}/end-users",
            headers=H,
            json={
                "external_id": external_id,
                "template_id": tier,
                "metadata": {"email": f"{external_id}@niapp.com"},
            },
            timeout=10.0,
        )
        print(f"    {external_id} -> {tier}")

    # ---------- D) Customers each log in + chat ----------
    print(
        "\n[D] Each customer logs in (Nia's backend mints a token via /end-users/{id}/tokens)."
    )
    user_tokens = {}
    for external_id, _ in customers:
        r = httpx.post(
            f"{base}/end-users/{external_id}/tokens",
            headers=H,
            json={"ttl_seconds": 3600},
            timeout=10.0,
        )
        user_tokens[external_id] = r.json()["token"]
        print(f"    minted token for {external_id} (jti={r.json()['token_id'][:8]}...)")

    print("\n    alice and carol each chat with the agent...")
    for external_id in ["alice", "carol"]:
        r = httpx.post(
            f"{base}/agents/research-agent/runs",
            headers={"Authorization": f"Bearer {user_tokens[external_id]}"},
            data={"message": f"hello from {external_id}", "stream": "false"},
            timeout=60.0,
        )
        print(f"    {external_id} chat -> {r.status_code}")

    # ---------- E) Admin upgrades bob to pro ----------
    print("\n[E] Admin upgrades bob from free to pro.")
    r = httpx.patch(
        f"{base}/end-users/bob",
        headers=H,
        json={"template_id": "pro-tier"},
        timeout=10.0,
    )
    print(f"    PATCH /end-users/bob -> {r.status_code}")
    r = httpx.post(
        f"{base}/end-users/bob/tokens",
        headers=H,
        json={"ttl_seconds": 3600},
        timeout=10.0,
    )
    print(f"    new token scopes: {r.json()['scopes']}")

    # ---------- F) Admin reviews audit log + data isolation ----------
    print("\n[F.1] Recent audit entries (latest 8):")
    r = httpx.get(f"{base}/audit-log?limit=8", headers=H, timeout=10.0)
    for entry in r.json():
        target = entry["external_id"] or "-"
        print(
            f"    {entry['timestamp'][:19]}  {entry['action']:18s} {target:8s} status={entry['status']}"
        )

    print("\n[F.2] Confirm per-user data isolation (alice and carol's sessions).")
    for external_id in ["alice", "carol"]:
        token = user_tokens[external_id]
        r = httpx.get(
            f"{base}/sessions",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        body = r.json()
        ids_seen = {s.get("user_id") for s in body.get("data", [])}
        print(f"    {external_id} sees user_ids: {ids_seen}")

    print("\n" + "=" * 70)
    print("Nia is now selling to 3 customers with one-line tier control,")
    print("full audit trail, and zero scope-mapping logic in their app code.")
    print("=" * 70)


if __name__ == "__main__":
    main()
