"""End-user RBAC: simulate two end-users with per-subject data isolation.

This is the killer use case: you (the developer) want to give YOUR users their
own scoped access to an Agno-powered agent. Each user gets a token whose `sub`
is their identifier. With user_isolation=True, AgentOS automatically threads
that sub into every DB read/write, so users only see their own sessions and
memories.

What it does:
1. Boots an AgentOS with user_isolation=True.
2. Mints tokens for alice and bob, both with the same scopes (agents:run,
   sessions:read/write, memories:read/write).
3. Has alice and bob each chat with the agent via HTTP, with their own tokens.
4. Lists sessions for each user -- proves alice does NOT see bob's session and
   vice versa.

Run:
    export AGNO_JWT_SIGNING_KEY="..."
    export OPENAI_API_KEY="..."
    .venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/02_end_user_simulation.py
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
db = SqliteDb(db_file="tmp/end_user_rbac_isolation.db")

chat_agent = Agent(
    id="chat-agent",
    name="Chat Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    add_history_to_context=True,
)

agent_os = AgentOS(
    id="multi-user-os",
    description="AgentOS demonstrating end-user data isolation",
    agents=[chat_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SIGNING_KEY],
        algorithm="HS256",
        verify_audience=True,
        audience="multi-user-os",
        user_isolation=True,
    ),
)

app = agent_os.get_app()


def run_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=7778, log_level="warning")


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    base = "http://127.0.0.1:7778"
    end_user_scopes = [
        "agents:read",
        "agents:chat-agent:run",
        "sessions:read",
        "sessions:write",
        "memories:read",
        "memories:write",
    ]

    alice_token = agent_os.issue_token(
        subject="alice", scopes=end_user_scopes, ttl_seconds=3600
    )
    bob_token = agent_os.issue_token(
        subject="bob", scopes=end_user_scopes, ttl_seconds=3600
    )

    print("=" * 70)
    print("End-user RBAC + per-subject data isolation demo")
    print("=" * 70)

    print("\n[alice] sending a chat...")
    r = httpx.post(
        f"{base}/agents/chat-agent/runs",
        headers=headers(alice_token),
        data={
            "message": "Remember that my favourite color is teal.",
            "stream": "false",
        },
        timeout=60.0,
    )
    print(f"  status={r.status_code}")

    print("\n[bob] sending a chat...")
    r = httpx.post(
        f"{base}/agents/chat-agent/runs",
        headers=headers(bob_token),
        data={
            "message": "Remember that I prefer Python over JavaScript.",
            "stream": "false",
        },
        timeout=60.0,
    )
    print(f"  status={r.status_code}")

    print("\n[alice] listing /sessions (should only show alice's session)...")
    r = httpx.get(f"{base}/sessions", headers=headers(alice_token), timeout=15.0)
    alice_sessions = r.json() if r.status_code == 200 else r.text
    print(f"  status={r.status_code}")
    print(f"  body={alice_sessions}")

    print("\n[bob] listing /sessions (should only show bob's session)...")
    r = httpx.get(f"{base}/sessions", headers=headers(bob_token), timeout=15.0)
    bob_sessions = r.json() if r.status_code == 200 else r.text
    print(f"  status={r.status_code}")
    print(f"  body={bob_sessions}")

    print("\n" + "=" * 70)
    if (
        isinstance(alice_sessions, dict)
        and isinstance(bob_sessions, dict)
        and "data" in alice_sessions
        and "data" in bob_sessions
    ):
        alice_user_ids = {s.get("user_id") for s in alice_sessions["data"]}
        bob_user_ids = {s.get("user_id") for s in bob_sessions["data"]}
        print(f"alice sees user_ids: {alice_user_ids}")
        print(f"bob   sees user_ids: {bob_user_ids}")
        if alice_user_ids == {"alice"} and bob_user_ids == {"bob"}:
            print("\nPASS: each end-user only sees their own sessions.")
        else:
            print("\nFAIL: cross-user data leaked.")
    print("=" * 70)


if __name__ == "__main__":
    main()
