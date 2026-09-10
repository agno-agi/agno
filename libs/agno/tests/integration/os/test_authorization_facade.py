"""The Authorization facade: one object for verification + roles + users + audit + admin API.

Covers the shapes the DX review asked for: a verify-only one-liner (no roles), managed roles wired
end to end through a served AgentOS (eager db and borrowed db), idempotent seeding, the auto-mounted
admin API, and the trust_token_scopes composite. The facade is a convenience layer over the same
primitives, so these assert behavior parity with the hand-assembled setup.
"""

import time

import pytest

pytest.importorskip("sqlalchemy")

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import Authorization  # noqa: E402

SECRET = "authz-facade-secret-at-least-256-bits-xxxxxxxxxx"
OS_ID = "facade-os"


def _token(sub, scopes=None, aud=OS_ID):
    payload = {"sub": sub, "aud": aud, "exp": int(time.time()) + 3600}
    if scopes is not None:
        payload["scopes"] = scopes
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _auth(sub, scopes=None):
    return {"Authorization": f"Bearer {_token(sub, scopes)}"}


class _MockRunOutput:
    def to_dict(self):
        return {"run_id": "r1"}


def _agents():
    return [Agent(id="research", name="R", db=InMemoryDb()), Agent(id="secret", name="S", db=InMemoryDb())]


# --------------------------------------------------------------------------- facade unit behavior


def test_verify_only_facade_builds_no_stores(tmp_path):
    """The common case: verification with no roles. No role store, no directory, provider falls back
    to scope RBAC. This is the one-liner an isolation / scope-based deployment writes."""
    db = SqliteDb(db_file=str(tmp_path / "vo.db"))
    authz = Authorization(verification_keys=[SECRET], audience=OS_ID, user_directory=False)
    authz._bind(db)
    assert authz.role_store is None
    assert authz.user_store is None
    cfg = authz.authorization_config()
    assert cfg.authorization_provider is None  # AgentOS defaults to ScopeAuthorizationProvider
    assert cfg.verification_keys == [SECRET] and cfg.audience == OS_ID


def test_borrowed_db_applies_buffered_definitions(tmp_path):
    """No db passed to Authorization: role/user definitions buffer, then apply when the OS db binds
    (the 'never pass db twice' path)."""
    authz = Authorization(audit=True)
    authz.define_role("runner", ["agents:*:run"])
    authz.seed(users=[("carol", {"email": "c@co", "role": "runner"})])
    assert authz._bound is False

    db = SqliteDb(db_file=str(tmp_path / "borrow.db"))
    authz._bind(db)
    assert authz.role_store.list_roles() == ["runner"]
    assert authz.role_store.roles_of("carol") == ["runner"]
    assert authz.user_store.get("carol") is not None


def test_seed_is_idempotent(tmp_path):
    """Seeding on every start is safe: single-role assigns and directory upserts are no-ops when
    unchanged, so a restart neither re-grants nor duplicates."""
    db = SqliteDb(db_file=str(tmp_path / "seed.db"))
    authz = Authorization(db=db)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    authz.seed(admin="root", users=[("bob", {"email": "bob@co", "role": "viewer"})])
    authz.seed(admin="root", users=[("bob", {"email": "bob@co", "role": "viewer"})])  # again
    assert authz.role_store.roles_of("root") == ["admin"]
    assert authz.role_store.roles_of("bob") == ["viewer"]
    assert authz.role_store.default_role() == "viewer"


# --------------------------------------------------------------------------- served end to end


def _served(tmp_path, *, borrow_db, trust_token_scopes=False):
    """AgentOS wired through the facade, either borrowing the OS db or holding its own."""
    db = SqliteDb(db_file=str(tmp_path / "served.db"))
    kwargs = dict(
        audit=True,
        trust_token_scopes=trust_token_scopes,
        verification_keys=[SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        auto_provision=True,
    )
    authz = Authorization(**kwargs) if borrow_db else Authorization(db=db, **kwargs)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    authz.define_role("runner", ["agents:research:read", "agents:research:run"])
    authz.seed(
        admin="root",
        users=[("bob", {"email": "bob@co", "name": "Bob", "role": "viewer"}), ("carol", {"role": "runner"})],
    )
    os_ = AgentOS(id=OS_ID, db=db, agents=_agents(), authorization=authz)
    return os_


@pytest.mark.parametrize("borrow_db", [True, False], ids=["borrowed-db", "own-db"])
def test_served_facade_enforces_roles(tmp_path, borrow_db):
    """Managed roles enforce end to end through a served AgentOS built from the facade, whether the
    facade borrows the OS db or holds its own."""
    from unittest.mock import AsyncMock, patch

    client = TestClient(_served(tmp_path, borrow_db=borrow_db).get_app())
    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        run = lambda sub, agent: client.post(  # noqa: E731
            f"/agents/{agent}/runs", headers=_auth(sub), data={"message": "hi", "stream": "false"}
        ).status_code
        assert run("carol", "secret") == 403  # runner has no secret grant
        assert run("carol", "research") == 200  # runner may run research
        assert run("root", "secret") == 200  # admin role bypass
        assert run("nobody", "research") == 403  # default role is viewer (read only), so a run is denied
        # ...but the unknown caller WAS JIT-provisioned with the default role, so a read is allowed
        # (an ungranted caller would be 403 here too) -- this is what proves the default grant fired.
        assert client.get("/agents/research", headers=_auth("nobody")).status_code == 200


def test_served_facade_list_filtering(tmp_path):
    """The list gate filters to the caller's accessible resources through the facade."""
    client = TestClient(_served(tmp_path, borrow_db=True).get_app())
    r = client.get("/agents", headers=_auth("carol"))
    assert r.status_code == 200
    assert sorted(a["id"] for a in r.json()) == ["research"]  # runner sees only research


def test_admin_api_auto_mounted_and_gated(tmp_path):
    """The facade mounts /authz and /users itself (no include_router), still admin-gated."""
    client = TestClient(_served(tmp_path, borrow_db=True).get_app())
    assert client.get("/authz/roles", headers=_auth("root")).status_code == 200
    assert client.get("/users", headers=_auth("root")).status_code == 200
    assert client.get("/authz/roles").status_code == 401  # unauth
    assert client.get("/authz/roles", headers=_auth("bob")).status_code == 403  # non-admin
    slugs = sorted(r["slug"] for r in client.get("/authz/roles", headers=_auth("root")).json()["data"])
    assert slugs == ["admin", "runner", "viewer"]


def test_trust_token_scopes_runs_both_planes(tmp_path):
    """trust_token_scopes composes a scope plane with the role store: an operator authorized purely
    by a token admin scope (no role) is allowed alongside role-based end users."""
    from unittest.mock import AsyncMock, patch

    client = TestClient(_served(tmp_path, borrow_db=True, trust_token_scopes=True).get_app())
    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        # operator: token carries the admin scope, has no role in the store
        r = client.post(
            "/agents/secret/runs",
            headers=_auth("operator", scopes=["agent_os:admin"]),
            data={"message": "hi", "stream": "false"},
        )
    assert r.status_code == 200


def test_bring_your_own_provider_overrides(tmp_path):
    """An explicit authorization_provider is used verbatim, so the facade never overrides a
    power-user's custom provider."""
    from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider

    class DenyAll(AuthorizationProvider):
        def check(self, ctx: AuthorizationContext) -> bool:
            return False

        def accessible_resource_ids(self, ctx: AuthorizationContext):
            return set()

    db = SqliteDb(db_file=str(tmp_path / "byo.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], audience=OS_ID, authorization_provider=DenyAll())
    assert isinstance(authz.authorization_config().authorization_provider, DenyAll)
