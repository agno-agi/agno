"""
Quick end-to-end test for RBAC scope enforcement.

Spins up an AgentOS with JWT auth and tests that:
1. User with agents:read can list agents but NOT run them
2. User with agents:run can run agents
3. User with workflows:read CANNOT run workflows
4. Components require components:write to create
5. Admin bypasses everything
6. WebSocket reports requires_auth: true when JWT is configured

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/rbac/test_scopes.py
"""

import json
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.workflow.workflow import Workflow
from fastapi.testclient import TestClient

JWT_SECRET = "test-secret-key-long-enough-for-hs256!!"
OS_ID = "test-os"


def make_token(user_id: str, scopes: list[str]) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "aud": OS_ID,
            "scopes": scopes,
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main():
    db = SqliteDb(db_file="/tmp/test_scopes.db")

    agent = Agent(id="test-agent", name="Test Agent", db=db, instructions="Say hello")

    async def noop_workflow(session_state):
        return "done"

    workflow = Workflow(
        id="test-workflow", name="Test Workflow", steps=noop_workflow, db=db
    )

    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        workflows=[workflow],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET], algorithm="HS256"
        ),
    )

    client = TestClient(agent_os.get_app())

    # Tokens with different scopes
    reader = make_token("reader", ["agents:read", "workflows:read", "sessions:read"])
    runner = make_token(
        "runner",
        [
            "agents:read",
            "agents:run",
            "workflows:run",
            "sessions:read",
            "sessions:write",
        ],
    )
    admin = make_token("admin", ["agent_os:admin"])
    no_components = make_token("user", ["agents:read"])

    results = []

    def check(desc: str, response, expected_status: int):
        ok = response.status_code == expected_status
        status = "PASS" if ok else "FAIL"
        results.append((status, desc))
        detail = ""
        if not ok:
            detail = f" (got {response.status_code}, body: {response.text[:200]})"
        print(f"  [{status}] {desc}{detail}")

    # --- Agents ---
    print("\nAgent endpoints:")
    check("reader can list agents", client.get("/agents", headers=auth(reader)), 200)
    check(
        "reader CANNOT run agent (no agents:run scope)",
        client.post(
            "/agents/test-agent/runs", data={"message": "hi"}, headers=auth(reader)
        ),
        403,
    )
    check(
        "runner CAN run agent",
        client.post(
            "/agents/test-agent/runs",
            data={"message": "hi", "stream": "false"},
            headers=auth(runner),
        ),
        200,
    )

    # --- Workflows ---
    print("\nWorkflow endpoints:")
    check(
        "reader can list workflows", client.get("/workflows", headers=auth(reader)), 200
    )
    check(
        "reader CANNOT run workflow (no workflows:run scope)",
        client.post(
            "/workflows/test-workflow/runs",
            data={"message": "hi"},
            headers=auth(reader),
        ),
        403,
    )

    # --- Components ---
    print("\nComponent endpoints:")
    check(
        "user without components:write CANNOT create component",
        client.post(
            "/components",
            json={"name": "test", "component_type": "agent"},
            headers=auth(no_components),
        ),
        403,
    )
    # Note: admin component create requires PostgresDb (SQLite doesn't support components table)
    # Skipping in this test — the scope enforcement (403 above) is the key validation

    # --- Admin bypass ---
    print("\nAdmin bypass:")
    check("admin can list agents", client.get("/agents", headers=auth(admin)), 200)
    check("admin can list sessions", client.get("/sessions", headers=auth(admin)), 200)

    # --- WebSocket ---
    print("\nWebSocket:")
    try:
        with client.websocket_connect("/workflows/ws") as ws:
            data = json.loads(ws.receive_text())
            ws_auth = data.get("requires_auth", None)
            ok = ws_auth is True
            status = "PASS" if ok else "FAIL"
            results.append((status, "WebSocket sends requires_auth: true"))
            print(f"  [{status}] WebSocket sends requires_auth: {ws_auth}")
    except Exception as e:
        results.append(("FAIL", f"WebSocket connection failed: {e}"))
        print(f"  [FAIL] WebSocket connection failed: {e}")

    # --- Summary ---
    passed = sum(1 for s, _ in results if s == "PASS")
    failed = sum(1 for s, _ in results if s == "FAIL")
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print("\nFailures:")
        for s, d in results:
            if s == "FAIL":
                print(f"  - {d}")
    print()

    # Cleanup
    import os

    os.unlink("/tmp/test_scopes.db") if os.path.exists("/tmp/test_scopes.db") else None

    return 1 if failed else 0


if __name__ == "__main__":
    exit(main())
