"""
End-to-end IDOR (Insecure Direct Object Reference) test for session isolation.

Spins up a real AgentOS with InMemoryDb and a fake auth middleware that sets
request.state.user_id from a custom X-Test-User-Id header.  Two "users"
(alice, bob) each create sessions, then attempt to read / delete / rename
the other user's session through the HTTP API.

When all tests PASS: the fix is working — cross-user access is blocked.
When tests FAIL: the vulnerability is present.

OWASP A01:2021 — Broken Access Control

Run:
    source .venv/bin/activate
    python -m pytest libs/agno/tests/unit/db/test_session_idor_poc.py -v
"""

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Fake auth middleware — simulates JWT setting request.state.user_id
# ---------------------------------------------------------------------------


class FakeAuthMiddleware(BaseHTTPMiddleware):
    """Sets request.state.user_id from an X-Test-User-Id header.
    This simulates what the real JWTMiddleware does after validating a token."""

    async def dispatch(self, request: Request, call_next):
        user_id = request.headers.get("x-test-user-id")
        request.state.user_id = user_id  # None if header absent
        response: Response = await call_next(request)
        return response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clients():
    """Create an AgentOS app with InMemoryDb and two TestClients (alice, bob)."""
    db = InMemoryDb()

    agent = Agent(
        name="test-agent",
        id="test-agent",
        model=OpenAIChat(id="gpt-4o"),
        db=db,
    )

    agent_os = AgentOS(agents=[agent], db=db, telemetry=False)
    app: FastAPI = agent_os.get_app()

    # Inject fake auth middleware — must be added AFTER get_app() so it runs
    # before the session router (Starlette middleware stack is LIFO)
    app.add_middleware(FakeAuthMiddleware)

    alice = TestClient(app, headers={"x-test-user-id": "alice"})
    bob = TestClient(app, headers={"x-test-user-id": "bob"})
    anon = TestClient(app)  # no user_id header

    return alice, bob, anon, db


def _create_session(client: TestClient, name: str, agent_id: str = "test-agent") -> str:
    """Create a session via the API, return the session_id."""
    resp = client.post(
        "/sessions",
        params={"type": "agent"},
        json={
            "session_name": name,
            "agent_id": agent_id,
        },
    )
    assert resp.status_code == 201, f"create failed: {resp.text}"
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# 1. Read isolation
# ---------------------------------------------------------------------------


class TestReadIsolation:
    def test_owner_can_read_own_session(self, clients):
        alice, bob, _, _ = clients
        sid = _create_session(alice, "Alice private")

        resp = alice.get(f"/sessions/{sid}", params={"type": "agent"})
        assert resp.status_code == 200
        assert resp.json()["session_id"] == sid

    def test_other_user_cannot_read_session(self, clients):
        alice, bob, _, _ = clients
        sid = _create_session(alice, "Alice private")

        resp = bob.get(f"/sessions/{sid}", params={"type": "agent"})
        assert resp.status_code == 404, f"IDOR: Bob read Alice's session! Got {resp.status_code}: {resp.text}"

    def test_list_sessions_scoped_by_user(self, clients):
        alice, bob, _, _ = clients
        _create_session(alice, "Alice 1")
        _create_session(alice, "Alice 2")
        _create_session(bob, "Bob 1")

        alice_list = alice.get("/sessions", params={"type": "agent"}).json()
        bob_list = bob.get("/sessions", params={"type": "agent"}).json()

        alice_names = {s["session_name"] for s in alice_list["data"]}
        bob_names = {s["session_name"] for s in bob_list["data"]}

        assert "Alice 1" in alice_names and "Alice 2" in alice_names
        assert "Bob 1" not in alice_names, "IDOR: Alice can see Bob's sessions"

        assert "Bob 1" in bob_names
        assert "Alice 1" not in bob_names, "IDOR: Bob can see Alice's sessions"


# ---------------------------------------------------------------------------
# 2. Delete isolation
# ---------------------------------------------------------------------------


class TestDeleteIsolation:
    def test_owner_can_delete_own_session(self, clients):
        alice, bob, _, _ = clients
        sid = _create_session(alice, "Alice to delete")

        resp = alice.delete(f"/sessions/{sid}")
        assert resp.status_code == 204

        # Verify it's gone
        resp = alice.get(f"/sessions/{sid}", params={"type": "agent"})
        assert resp.status_code == 404

    def test_other_user_cannot_delete_session(self, clients):
        alice, bob, _, _ = clients
        sid = _create_session(alice, "Alice protected")

        resp = bob.delete(f"/sessions/{sid}")
        # Should either 404 (session not found for bob) or 204 with no effect
        # Either way, Alice's session must survive
        resp = alice.get(f"/sessions/{sid}", params={"type": "agent"})
        assert resp.status_code == 200, f"IDOR: Bob deleted Alice's session! Got {resp.status_code}"

    def test_bulk_delete_scoped_by_user(self, clients):
        alice, bob, _, _ = clients
        alice_sid = _create_session(alice, "Alice bulk")
        bob_sid = _create_session(bob, "Bob bulk")

        # Bob tries to bulk-delete both sessions
        resp = bob.request(
            "DELETE",
            "/sessions",
            json={
                "session_ids": [alice_sid, bob_sid],
                "session_types": ["agent", "agent"],
            },
        )

        # Bob's should be gone, Alice's should survive
        assert bob.get(f"/sessions/{bob_sid}", params={"type": "agent"}).status_code == 404
        resp = alice.get(f"/sessions/{alice_sid}", params={"type": "agent"})
        assert resp.status_code == 200, f"IDOR: Bob bulk-deleted Alice's session! Got {resp.status_code}"


# ---------------------------------------------------------------------------
# 3. Rename isolation
# ---------------------------------------------------------------------------


class TestRenameIsolation:
    def test_owner_can_rename_own_session(self, clients):
        alice, bob, _, _ = clients
        sid = _create_session(alice, "Original name")

        resp = alice.post(
            f"/sessions/{sid}/rename",
            params={"type": "agent"},
            json={"session_name": "New name"},
        )
        assert resp.status_code == 200
        assert resp.json()["session_name"] == "New name"

    def test_other_user_cannot_rename_session(self, clients):
        alice, bob, _, _ = clients
        sid = _create_session(alice, "Alice original")

        resp = bob.post(
            f"/sessions/{sid}/rename",
            params={"type": "agent"},
            json={"session_name": "Hacked by Bob"},
        )
        # Should be 404 (session not found for bob's user_id)
        assert resp.status_code == 404, f"IDOR: Bob renamed Alice's session! Got {resp.status_code}: {resp.text}"

        # Verify name unchanged
        resp = alice.get(f"/sessions/{sid}", params={"type": "agent"})
        assert resp.status_code == 200
        assert resp.json()["session_name"] == "Alice original", "IDOR: Alice's session name was changed by Bob"
