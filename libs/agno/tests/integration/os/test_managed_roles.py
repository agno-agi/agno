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


def test_managed_roles_enforce_on_rest_gate_via_shortcut(tmp_path):
    """The payoff, end to end on the v2.7 REST route gate: an AgentOS wired with the
    ``role_store=`` shortcut (no manual .provider) enforces a managed role for a caller
    whose JWT carries NO scopes at all — the ``viewer`` role (agents:*:read) is resolved
    from the store, not the token. Same viewer, same token: GET /agents/{id} is 200 but
    POST /agents/{id}/runs is 403, proving action granularity flows through the same gate
    that v2.7 gates scopes on. With no provider configured this gate is byte-identical
    scope RBAC; here it is managed roles, at the very same choke point."""
    from agno.db.sqlite import SqliteDb

    store = ManagedRoleStore()  # no DB of its own -> AgentOS adopts the OS DB
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
            role_store=store,  # the shortcut: AgentOS binds the OS db + uses store.provider
        ),
    )
    client = TestClient(agent_os.get_app())

    # viewer = read-only on agents; assigned to bob via the store (not via any token scope)
    store.set_role_scopes("viewer", ["agents:*:read"])
    store.assign("bob", "viewer")

    # The token carries scopes: [] — authorization comes entirely from the managed role.
    assert jwt.decode(_token("bob"), SECRET, algorithms=["HS256"], audience=OS_ID)["scopes"] == []

    # read allowed, run denied — same subject, same (empty-scope) token
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 200
    assert client.post("/agents/research-agent/runs", headers=_auth("bob"), data={"message": "hi"}).status_code == 403


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


def test_deny_override_is_not_leaked_by_the_list_endpoint():
    """Regression: a per-resource deny must be carved out of GET /agents, not just
    the per-resource gate.

    The deny-aware ``filter_accessible`` was previously dead on the request path:
    the route gate cached an allow-only ``accessible_resource_ids`` of ``{"*"}`` on
    ``request.state`` and the listing short-circuited on it, so ``GET /agents/{id}``
    correctly 403'd while ``GET /agents`` still returned the denied agent's full
    response body. This drives real HTTP so the whole pipeline is covered.
    """
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("analyst", [("agents:*:read", "allow"), ("agents:other-agent:read", "deny")])
    store.assign("bob", "analyst")
    client = _build(store)
    headers = {"Authorization": f"Bearer {_token('bob')}"}

    # the per-resource gate denies the excluded agent...
    assert client.get("/agents/other-agent", headers=headers).status_code == 403
    assert client.get("/agents/research-agent", headers=headers).status_code == 200

    # ...and the listing must agree, rather than disclosing it
    listing = client.get("/agents", headers=headers)
    assert listing.status_code == 200
    assert {a["id"] for a in listing.json()} == {"research-agent"}


def test_wildcard_allow_without_denies_still_lists_everything():
    """The narrowing added for deny-overrides must not over-filter the common case."""
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("reader", ["agents:*:read"])
    store.assign("ana", "reader")
    client = _build(store)

    listing = client.get("/agents", headers={"Authorization": f"Bearer {_token('ana')}"})
    assert listing.status_code == 200
    assert {a["id"] for a in listing.json()} == {"research-agent", "other-agent"}


def test_per_resource_grant_lists_only_that_resource():
    """A caller holding only a concrete per-resource scope (the path that populates
    the request-state id cache) still sees exactly their one agent."""
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("narrow", ["agents:research-agent:read"])
    store.assign("nick", "narrow")
    client = _build(store)

    listing = client.get("/agents", headers={"Authorization": f"Bearer {_token('nick')}"})
    assert listing.status_code == 200
    assert {a["id"] for a in listing.json()} == {"research-agent"}


def test_concurrent_assign_keeps_exactly_one_role():
    """Regression: assign() must be atomic.

    It was read-then-unassign-then-assign across three transactions. Two concurrent
    assigns each cleared only the role their stale read had seen, so the subject ended
    up durably holding BOTH -- a demote racing any other change silently left the user
    with the privileged role they were supposed to lose. The same gap also left a window
    with zero roles, denying requests in flight during any ordinary role change.
    """
    import threading

    store = ManagedRoleStore(db_url=_db_url())
    for role in ("base", "admin", "member"):
        store.set_role_scopes(role, ["agents:*:read"])

    for _ in range(25):
        store.assign("bob", "base")  # neither contender equals the current role
        barrier = threading.Barrier(2)

        def assign_role(role):
            barrier.wait()
            store.assign("bob", role)

        threads = [threading.Thread(target=assign_role, args=(r,)) for r in ("admin", "member")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        roles = store.roles_of("bob")
        assert len(roles) == 1, f"one role per subject violated: {roles}"
        assert roles[0] in ("admin", "member")
