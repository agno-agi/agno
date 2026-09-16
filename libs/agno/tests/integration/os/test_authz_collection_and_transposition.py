"""Three regressions on the managed-roles surface.

1. A collection request (create, or list) carries no resource id. The engine used to evaluate it
   against the bare type (``agents``), which no policy row ever matches, so a role holding
   ``agents:write`` (stored as ``agents/*``) was refused on ``POST /agents`` even though
   ``check_scope`` on the same grant said yes. It is now evaluated as ``type/*``. The list route
   must keep filtering for a role that holds only a single id, rather than 403.
2. Subjects and roles share the grouping table, so ``assign("viewer", "admin")`` with the arguments
   transposed made the role ``viewer`` inherit ``admin``: every viewer became an admin. The store
   refuses a subject that is a role slug, and the admin API turns that into a 400.
3. ``supports_authz`` treated any exception but ``NotImplementedError`` as "supported but down",
   so a plain ``object()`` passed boot and failed on the first request.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")  # managed roles persist/enforce via the native engine + SQLAlchemy

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import Authorization, RoleStore  # noqa: E402
from agno.os.authz._db import supports_authz  # noqa: E402

SECRET = "collection-transposition-secret-at-least-256-bits-long-xx"
OS_ID = "collection-transposition-os"


def _auth(sub: str) -> dict:
    token = jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _served(tmp_path):
    """Two agents, three roles: one may create sessions, one may read one agent, one is admin."""
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("builder", ["sessions:write", "sessions:read", "agents:*:read"])
    authz.define_role("narrow", ["agents:research-agent:read"])
    authz.seed(admin="alice")
    authz.assign("bob", "builder")
    authz.assign("carol", "narrow")
    os_ = AgentOS(
        id=OS_ID,
        db=db,
        agents=[Agent(id="research-agent", name="R", db=db), Agent(id="other-agent", name="O", db=db)],
        authorization=authz,
    )
    return TestClient(os_.get_app()), authz.role_store


# ------------------------------------------------------------------ 1. collection requests
def test_two_part_write_scope_passes_the_collection_route(tmp_path):
    """``sessions:write`` is stored as ``sessions/*``; a create on the collection must be evaluated
    against that same key, so the holder can actually create."""
    client, store = _served(tmp_path)
    engine = store._engine

    # the engine agrees with itself: the scope check and the id-less resource check say the same
    assert engine.check_scope("sessions:write", subject="bob") is True
    assert engine.check_resource("sessions", None, "write", subject="bob") is True
    assert engine.check_resource("sessions", "some-id", "write", subject="bob") is True
    # and a grant on one id does not become a grant on the collection
    assert engine.check_resource("agents", None, "read", subject="carol") is False
    assert engine.check_resource("agents", "research-agent", "read", subject="carol") is True

    body = {"session_type": "agent", "agent_id": "research-agent", "session_name": "made by bob"}
    r = client.post("/sessions", headers=_auth("bob"), json=body)
    assert r.status_code == 201, r.text
    # narrow holds no sessions scope at all: still refused
    assert client.post("/sessions", headers=_auth("carol"), json=body).status_code == 403


def test_list_gate_still_filters_for_a_single_id_grant(tmp_path):
    """A role holding one agent must get a filtered list on ``GET /agents``, not a 403, and the
    collection-wide reader sees both."""
    client, _ = _served(tmp_path)
    narrow = client.get("/agents", headers=_auth("carol"))
    assert narrow.status_code == 200, narrow.text
    assert [a["id"] for a in narrow.json()] == ["research-agent"]
    wide = client.get("/agents", headers=_auth("bob"))
    assert wide.status_code == 200
    assert sorted(a["id"] for a in wide.json()) == ["other-agent", "research-agent"]
    # narrow can read its one agent, not the other
    assert client.get("/agents/research-agent", headers=_auth("carol")).status_code == 200
    assert client.get("/agents/other-agent", headers=_auth("carol")).status_code == 403


# ------------------------------------------------------------------ 2. transposed assign
def test_store_refuses_a_role_slug_as_the_subject(tmp_path):
    """``assign("viewer", "admin")`` would make every viewer an admin through role inheritance."""
    roles = RoleStore(db=SqliteDb(db_file=str(tmp_path / "roles.db")))
    roles.set_role_scopes("admin", ["agent_os:admin"])
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("carol", "viewer")
    assert roles.can_manage("carol") is False

    with pytest.raises(ValueError, match="'viewer' is a role, not a user"):
        roles.assign("viewer", "admin")

    assert roles.roles_of("viewer") == []  # nothing was written
    assert roles.can_manage("carol") is False  # and carol is still just a viewer
    # a role that exists only as metadata (created in the UI, no scopes yet) is a role too
    roles.create_role("drafts", name="Drafts")
    with pytest.raises(ValueError, match="'drafts' is a role"):
        roles.assign("drafts", "admin")
    # the intended direction still works
    roles.assign("dave", "admin")
    assert roles.can_manage("dave") is True


def test_authorization_assign_inherits_the_guard(tmp_path):
    """Both spellings go through the store: an eager object (db given) refuses at the call, a
    buffered one (db borrowed from AgentOS) refuses when AgentOS binds it."""
    db = SqliteDb(db_file=str(tmp_path / "authz.db"))
    eager = Authorization(db=db, verification_keys=[SECRET], audience=OS_ID)
    eager.define_role("admin", ["agent_os:admin"])
    eager.define_role("viewer", ["agents:*:read"])
    with pytest.raises(ValueError, match="'viewer' is a role"):
        eager.assign("viewer", "admin")
    assert eager.role_store.roles_of("viewer") == []

    buffered = Authorization(verification_keys=[SECRET], audience=OS_ID)
    buffered.define_role("admin", ["agent_os:admin"])
    buffered.define_role("viewer", ["agents:*:read"])
    buffered.assign("viewer", "admin")  # nothing to check against yet: applied at bind
    with pytest.raises(ValueError, match="'viewer' is a role"):
        AgentOS(
            id=OS_ID,
            db=SqliteDb(db_file=str(tmp_path / "os.db")),
            agents=[Agent(id="a", name="A", db=InMemoryDb())],
            authorization=buffered,
        )


def test_admin_api_turns_the_transposed_call_into_a_400(tmp_path):
    client, store = _served(tmp_path)
    store.set_role_scopes("viewer", ["agents:*:read"])
    store.assign("erin", "viewer")

    r = client.post("/authz/subjects/viewer/roles", headers=_auth("alice"), json={"role": "admin"})
    assert r.status_code == 400, r.text
    assert "is a role, not a user" in r.json()["detail"]
    assert store.roles_of("viewer") == []
    # erin, a viewer, did not become an admin
    assert client.get("/authz/roles", headers=_auth("erin")).status_code == 403
    # the same call the right way round still works
    ok = client.post("/authz/subjects/erin/roles", headers=_auth("alice"), json={"role": "admin"})
    assert ok.status_code == 200 and ok.json()["role"] == "admin"


# ------------------------------------------------------------------ 3. supports_authz probe
def test_supports_authz_rejects_a_non_database_object(tmp_path):
    from unittest.mock import patch

    assert supports_authz(object()) is False  # not an agno database: no contract to implement
    assert supports_authz(None) is False
    assert supports_authz(InMemoryDb()) is False  # inherits the NotImplementedError stubs
    real = SqliteDb(db_file=str(tmp_path / "s.db"))
    assert supports_authz(real) is True
    # a real backend whose probe fails for a reason other than the contract is still supported
    with patch.object(SqliteDb, "authz_name_is_role", side_effect=ConnectionError("db is down")):
        assert supports_authz(real) is True
