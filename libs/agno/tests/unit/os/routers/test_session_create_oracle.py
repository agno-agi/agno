"""create_session must not leak another user's session existence/ownership.

The pre-create 409 conflict check used to call get_session without user_id, so
a scoped caller could POST an arbitrary session_id and distinguish "another
user's session exists" from "free id", and was steered to PATCH a session it
could not read. session_id is a global primary key, so id-occupancy is
inherent, but the response must never confirm ownership or steer to PATCH a
session outside the caller's scope.
"""

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from agno.db.sqlite import SqliteDb
from agno.os.routers.session.session import get_session_router
from agno.os.settings import AgnoAPISettings
from agno.session import AgentSession


@pytest.fixture
def db():
    d = SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "sessions.db"))
    d.upsert_session(AgentSession(session_id="bob-private", user_id="bob", agent_id="a1"))
    d.upsert_session(AgentSession(session_id="alice-own", user_id="alice", agent_id="a1"))
    return d


def _client(db, scoped_user):
    app = FastAPI()
    app.include_router(get_session_router({"default": [db]}, AgnoAPISettings()))

    class ScopedJWT(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if scoped_user is not None:
                request.state.user_id = scoped_user
                request.state.user_isolation_enabled = True
                request.state.scopes = []
            return await call_next(request)

    if scoped_user is not None:
        app.add_middleware(ScopedJWT)
    return TestClient(app, raise_server_exceptions=False)


class TestScopedCaller:
    def test_cross_owner_collision_hides_ownership(self, db):
        resp = _client(db, "alice").post("/sessions?type=agent", json={"session_id": "bob-private"})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        # Must not confirm the id/ownership or steer to a PATCH alice cannot perform.
        assert "bob-private" not in detail
        assert "PATCH" not in detail
        assert "already exists" not in detail

    def test_own_collision_stays_informative(self, db):
        resp = _client(db, "alice").post("/sessions?type=agent", json={"session_id": "alice-own"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]
        assert "PATCH" in resp.json()["detail"]

    def test_free_id_creates(self, db):
        resp = _client(db, "alice").post("/sessions?type=agent", json={"session_id": "brand-new"})
        assert resp.status_code in (200, 201)

    def test_cross_owner_probe_never_overwrites(self, db):
        _client(db, "alice").post("/sessions?type=agent", json={"session_id": "bob-private"})
        row = db.get_session(session_id="bob-private", user_id="bob")
        assert row is not None and row.user_id == "bob"


class TestUnscopedCallerUnchanged:
    def test_admin_or_isolation_off_gets_informative_409(self, db):
        # No scoping middleware => get_scoped_user_id returns None => original behaviour.
        resp = _client(db, None).post("/sessions?type=agent", json={"session_id": "bob-private"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]
