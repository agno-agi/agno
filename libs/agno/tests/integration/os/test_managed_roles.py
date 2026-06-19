"""Integration tests for ManagedRoleStore — the agno-native managed-roles tier.

Verifies the governance product surface end to end: roles defined in agno scope
terms, runtime assign/revoke, persistence to a DB, and enforcement through the
AgentOS request pipeline via the store's provider. No engine types appear in the
test body — the same as user code.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")  # managed roles persist/enforce via the native engine + SQLAlchemy

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402

SECRET = "managed-roles-test-secret-at-least-256-bits-long-xxxxx"
OS_ID = "managed-roles-test-os"


def _db_url() -> str:
    """A throwaway file-backed SQLite URL. Managed roles require a DB (no in-memory
    mode); file-backed so the same DB is visible across the threads TestClient uses."""
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".authz.db")
    os.close(fd)
    return f"sqlite:///{path}"


def _token(sub: str) -> str:
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET,
        algorithm="HS256",
    )


def _build(store: ManagedRoleStore) -> TestClient:
    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    other = Agent(id="other-agent", name="Other Agent", db=InMemoryDb())
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent, other],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=store.provider,
        ),
    )
    return TestClient(agent_os.get_app())


def _auth(sub: str) -> dict:
    return {"Authorization": f"Bearer {_token(sub)}"}


def test_role_scopes_enforced_through_pipeline():
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("viewer", ["agents:*:read"])
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("bob", "viewer")
    store.assign("alice", "admin")
    client = _build(store)

    # viewer can read
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 200
    # viewer cannot run
    r = client.post("/agents/research-agent/runs", headers=_auth("bob"), data={"message": "hi"})
    assert r.status_code == 403
    # admin can run
    r = client.post("/agents/research-agent/runs", headers=_auth("alice"), data={"message": "hi"})
    assert r.status_code != 403


def test_unassigned_subject_is_denied():
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("viewer", ["agents:*:read"])
    client = _build(store)
    assert client.get("/agents/research-agent", headers=_auth("nobody")).status_code == 403


def test_runtime_grant_takes_effect_same_token():
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("member", ["agents:*:read", "agents:research-agent:run"])
    client = _build(store)

    # bob has no role yet -> denied to run, with a stable token
    headers = _auth("bob")
    assert client.post("/agents/research-agent/runs", headers=headers, data={"message": "hi"}).status_code == 403

    # grant at runtime; SAME token
    store.assign("bob", "member")
    assert client.post("/agents/research-agent/runs", headers=headers, data={"message": "hi"}).status_code != 403

    # revoke at runtime; SAME token
    store.unassign("bob", "member")
    assert client.post("/agents/research-agent/runs", headers=headers, data={"message": "hi"}).status_code == 403


def test_per_resource_scope_is_granular():
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("member", ["agents:*:read", "agents:research-agent:run"])
    store.assign("bob", "member")
    client = _build(store)

    # may run the specific agent
    assert client.post("/agents/research-agent/runs", headers=_auth("bob"), data={"message": "hi"}).status_code != 403
    # but not a different one
    assert client.post("/agents/other-agent/runs", headers=_auth("bob"), data={"message": "hi"}).status_code == 403


def test_roles_from_external_idp_claim():
    """Roles carried on the token (external IdP) authorize against the same store."""
    store = ManagedRoleStore(roles_claim="roles", db_url=_db_url())
    store.set_role_scopes("editor", ["agents:*:read", "agents:research-agent:run"])
    client = _build(store)

    # token carries roles=["editor"]; sub is unknown to the store
    tok = jwt.encode(
        {
            "sub": "idp-user-999",
            "aud": OS_ID,
            "scopes": [],
            "roles": ["editor"],
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {tok}"}
    assert client.post("/agents/research-agent/runs", headers=headers, data={"message": "hi"}).status_code != 403


def test_non_resource_routes_are_gated_sessions():
    """Sessions endpoints (which the middleware can't tag with a resource_type)
    are governed by the same role policy — read/write/delete enforced, not open.
    """
    from agno.session import AgentSession

    db = InMemoryDb()
    db.upsert_session(AgentSession(session_id="s1", agent_id="research-agent", user_id="u"))

    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("support", ["sessions:read"])  # read only
    store.set_role_scopes("operator", ["sessions:read", "sessions:delete"])
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("bob", "support")
    store.assign("val", "operator")
    store.assign("alice", "admin")

    agent = Agent(id="research-agent", name="Research Agent", db=db)
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=store.provider,
        ),
    )
    client = TestClient(agent_os.get_app())

    # support can view but NOT delete (the gap this closes: previously open)
    assert client.get("/sessions?type=agent", headers=_auth("bob")).status_code == 200
    assert client.delete("/sessions/s1", headers=_auth("bob")).status_code == 403
    # operator can delete
    assert client.delete("/sessions/s1", headers=_auth("val")).status_code != 403
    # admin can view
    assert client.get("/sessions?type=agent", headers=_auth("alice")).status_code == 200
    # a subject with no role is denied even on a non-resource route
    assert client.get("/sessions?type=agent", headers=_auth("nobody")).status_code == 403


def test_management_helpers():
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("a", ["agents:*:read"])
    store.set_role_scopes("b", ["teams:*:read"])
    store.assign("bob", "a")
    assert store.roles_of("bob") == ["a"]
    # One role per subject: assigning another REPLACES, never stacks.
    store.assign("bob", "b")
    assert set(store.list_roles()) == {"a", "b"}
    assert store.roles_of("bob") == ["b"]
    # Re-assigning the same role is a no-op.
    store.assign("bob", "b")
    assert store.roles_of("bob") == ["b"]
    store.unassign("bob", "b")
    assert store.roles_of("bob") == []


def test_role_store_shortcut_wires_provider_and_defaults_os_db(tmp_path):
    """#4: AuthorizationConfig(role_store=...) wires the store's provider (no manual
    .provider). #3: a store with no DB of its own adopts the OS DB when AgentOS wires
    it (a DB is required — there is no in-memory mode), and roles persist there."""
    from agno.db.sqlite import SqliteDb

    store = ManagedRoleStore()  # no DB yet -> AgentOS will adopt the OS DB
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    agent = Agent(id="research-agent", name="R", db=db)
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            role_store=store,  # <- the shortcut; AgentOS adopts the OS db + uses store.provider
        ),
    )
    client = TestClient(agent_os.get_app())  # adopts the OS DB -> store is now bound

    # configure after wiring (the store is bound to the OS DB now)
    store.set_role_scopes("viewer", ["agents:*:read"])
    store.assign("bob", "viewer")
    assert store.is_bound is True
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 200
    assert client.get("/agents/research-agent", headers=_auth("nobody")).status_code == 403

    # roles persisted to the OS DB -> a fresh store on the same DB sees them
    fresh = ManagedRoleStore(db=db)
    assert fresh.roles_of("bob") == ["viewer"]
    assert fresh.get_role_scopes("viewer") == ["agents:read"]


def test_role_store_and_provider_are_mutually_exclusive():
    from agno.os.authz.scope_provider import ScopeAuthorizationProvider

    with pytest.raises(ValueError, match="not both"):
        AuthorizationConfig(role_store=ManagedRoleStore(), authorization_provider=ScopeAuthorizationProvider())


def test_role_store_without_any_db_fails_loud_at_wiring():
    """A managed store with no DB, wired into an AgentOS that also has no SQL DB,
    must fail loudly rather than silently run an in-memory store that can't stay
    consistent across replicas."""
    store = ManagedRoleStore()  # no DB
    agent = Agent(id="research-agent", name="R", db=InMemoryDb())  # not SQL-capable
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            role_store=store,
        ),
    )
    with pytest.raises(ValueError, match="needs a SQL database"):
        agent_os.get_app()
