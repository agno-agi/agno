"""User directory and per-user isolation as identity features, usable with no auth.

The directory is a roster and isolation scopes a run's own data; both key off the run's user_id.
With no auth that id is self-asserted, so they work (for local/demo/cookbooks) but are advisory,
not enforced. This is the ``AgentOS(db=db, user_isolation=True, user_directory=True)`` shape.
"""

import pytest

pytest.importorskip("sqlalchemy")

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.config import AuthorizationConfig, UserDirectoryConfig  # noqa: E402


def _os(tmp_path, **kw):
    return AgentOS(
        id="dir-os",
        agents=[Agent(id="research-agent", name="R", db=InMemoryDb())],
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        **kw,
    )


class _MockRunOutput:
    def to_dict(self):
        return {"run_id": "r1"}


def test_snippet_builds_directory_and_isolation_without_auth(tmp_path):
    """The exact shape asked for: AgentOS(db=db, user_isolation=True, user_directory=True), no
    auth. It builds (with an advisory warning), the bare True directory auto-provisions, and a
    tokenless run as chegizkhan registers him."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    os_ = _os(tmp_path, user_isolation=True, user_directory=True)
    assert os_.user_isolation is True
    assert os_.user_directory.auto_provision is True  # bare True defaults auto_provision on

    client = TestClient(os_.get_app())
    assert os_.user_directory.user_store.get("chegizkhan") is None

    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        r = client.post(
            "/agents/research-agent/runs",
            data={"message": "hi", "stream": "false", "user_id": "chegizkhan"},
        )
    assert r.status_code == 200, r.text
    assert os_.user_directory.user_store.get("chegizkhan") is not None  # roster populated from the run


def test_no_auth_directory_does_not_enforce_disabled(tmp_path):
    """Without auth the disabled flag is ADVISORY, not a kill-switch: the id is self-asserted, so
    a run is NOT blocked. Enforcement is a property of authorization."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from agno.os.authz.user_store import ManagedUserStore

    store = ManagedUserStore(db=SqliteDb(db_file=str(tmp_path / "dir.db")))
    store.upsert("chegizkhan", name="Chegiz")
    store.set_disabled("chegizkhan", True)

    os_ = _os(tmp_path, user_directory=UserDirectoryConfig(user_store=store, auto_provision=True))
    client = TestClient(os_.get_app())

    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        r = client.post(
            "/agents/research-agent/runs",
            data={"message": "hi", "stream": "false", "user_id": "chegizkhan"},
        )
    assert r.status_code == 200, r.text  # NOT blocked: disabled is advisory without auth
    assert store.get("chegizkhan")["disabled"] is True  # still flagged, simply not enforced here


def test_authenticated_directory_is_not_double_provisioned_by_the_run_hook(tmp_path):
    """The no-auth run hook must stay dormant when a token was verified: the middleware already
    provisioned/enforced, so sync_directory_from_request is a no-op on authenticated requests."""
    from agno.os.middleware.user_scope import sync_directory_from_request

    class _State:
        authenticated = True

    class _App:
        state = type("S", (), {"user_store": object(), "user_auto_provision": True})()

    class _Req:
        state = _State()
        app = _App()

    # Would raise if it tried to use the bogus user_store; the authenticated short-circuit
    # returns before touching it.
    sync_directory_from_request(_Req(), "someone")


def test_user_isolation_top_level_flag_wires_through_under_auth(tmp_path):
    """The top-level user_isolation flag reaches enforcement: with authorization on, the OS records
    isolation enabled on app.state (what get_scoped_user_id and the DB wrapper read)."""
    secret = "isolation-flag-secret-at-least-256-bits-xxxxxxxxx"
    os_ = _os(
        tmp_path,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[secret], algorithm="HS256"),
        user_isolation=True,
    )
    app = os_.get_app()
    assert getattr(app.state, "user_isolation_enabled", False) is True


def test_no_auth_provisioning_is_run_only(tmp_path):
    """No-auth provisioning is restricted to RUN endpoints (a run has intent to use the system). A
    plain GET carrying a user_id does NOT provision -- otherwise an open instance would be an
    unauthenticated roster/audit flooding primitive (GET ?user_id=<random> per id). Runs still fill
    the roster."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    os_ = _os(tmp_path, user_directory=True)  # bare True -> auto_provision on
    client = TestClient(os_.get_app())

    # a GET with a user_id must NOT provision
    client.get("/agents/research-agent", params={"user_id": "ghost"})
    assert os_.user_directory.user_store.get("ghost") is None

    # a run DOES provision
    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        r = client.post(
            "/agents/research-agent/runs",
            data={"message": "hi", "stream": "false", "user_id": "realrunner"},
        )
    assert r.status_code == 200, r.text
    assert os_.user_directory.user_store.get("realrunner") is not None


def test_user_isolation_without_auth_sets_scoping_but_does_not_provision(tmp_path):
    """user_isolation must work without auth: the no-auth identity middleware reads the self-asserted
    user_id and sets request.state (user_id + user_isolation_enabled) so get_scoped_user_id scopes to
    it. It does NOT provision the directory (scoping is read-only; provisioning is run-only). Tested
    at the middleware directly (no endpoint noise)."""
    import asyncio
    from types import SimpleNamespace

    from starlette.requests import Request

    from agno.os.authz.user_store import ManagedUserStore
    from agno.os.middleware.no_auth_identity import NoAuthIdentityMiddleware
    from agno.os.middleware.user_scope import get_scoped_user_id

    store = ManagedUserStore(db=SqliteDb(db_file=str(tmp_path / "m.db")))
    app_obj = SimpleNamespace(
        state=SimpleNamespace(
            user_store=store,
            user_auto_provision=True,
            role_store=None,
            user_default_role=None,
            user_email_claim="email",
            user_name_claim="name",
        )
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "query_string": b"user_id=zara",
        "headers": [],
        "app": app_obj,
        "state": {},
    }
    request = Request(scope)

    captured = {}

    async def call_next(req):
        captured["scoped"] = get_scoped_user_id(req)  # what a downstream read would scope to
        return SimpleNamespace(status_code=200)

    mw = NoAuthIdentityMiddleware(app=None, user_isolation=True)
    asyncio.run(mw.dispatch(request, call_next))

    assert captured["scoped"] == "zara"  # isolation scopes to the self-asserted id
    assert store.get("zara") is None  # scoping is read-only: the middleware does NOT provision


def test_no_auth_isolation_without_a_user_id_stays_unscoped_not_403(tmp_path):
    """Advisory, not enforced: with no auth and no user_id on the request, isolation must fall back
    to unscoped (None) rather than 403 -- there is no verified identity to fail closed on."""
    import asyncio
    from types import SimpleNamespace

    from starlette.requests import Request

    from agno.os.middleware.no_auth_identity import NoAuthIdentityMiddleware
    from agno.os.middleware.user_scope import get_scoped_user_id

    app_obj = SimpleNamespace(state=SimpleNamespace(user_store=None, user_auto_provision=False))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "query_string": b"",
        "headers": [],
        "app": app_obj,
        "state": {},
    }
    request = Request(scope)

    captured = {}

    async def call_next(req):
        captured["scoped"] = get_scoped_user_id(req)
        return SimpleNamespace(status_code=200)

    mw = NoAuthIdentityMiddleware(app=None, user_isolation=True)
    asyncio.run(mw.dispatch(request, call_next))
    assert captured["scoped"] is None  # no id -> unscoped, no 403


def test_users_admin_api_requires_auth_even_on_a_no_auth_instance(tmp_path):
    """The /users (and /authz) admin API is admin-gated and always requires a verified identity --
    it is NOT auto-opened on a no-auth instance. Inferring "open" from "no agno auth config" is
    unsafe (a third-party auth proxy sets nothing agno can see, so the gate would fail open). Serve
    the admin API under authorization (see manage_users.py) or manage the directory via the store."""
    from fastapi.testclient import TestClient

    from agno.os.authz.role_router import get_users_router
    from agno.os.authz.user_store import ManagedUserStore

    store = ManagedUserStore(db=SqliteDb(db_file=str(tmp_path / "u.db")))
    os_ = _os(tmp_path, user_directory=UserDirectoryConfig(user_store=store, auto_provision=True))
    app = os_.get_app()
    app.include_router(get_users_router(store))
    client = TestClient(app)
    assert client.get("/users").status_code == 401  # admin API is not auto-opened


def test_no_auth_run_refuses_a_reserved_principal(tmp_path):
    """A self-asserted run user_id must never claim a system-reserved principal (sa:*, __scheduler__):
    every other intake refuses these, so the no-auth run path must too. Otherwise user_id=sa:victim
    would land runs in that service account's history."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from agno.os.authz.user_store import ManagedUserStore

    store = ManagedUserStore(db=SqliteDb(db_file=str(tmp_path / "u.db")))
    os_ = _os(tmp_path, user_isolation=True, user_directory=UserDirectoryConfig(user_store=store, auto_provision=True))
    client = TestClient(os_.get_app())

    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        for uid in ("sa:backend", "__scheduler__", "realuser"):
            client.post(
                "/agents/research-agent/runs",
                data={"message": "hi", "stream": "false", "user_id": uid},
            )
    assert store.get("sa:backend") is None  # reserved -> refused
    assert store.get("__scheduler__") is None  # reserved -> refused
    assert store.get("realuser") is not None  # normal -> provisioned


def test_role_store_still_requires_authorization(tmp_path):
    """Unchanged by the directory/isolation relaxation: a role_store (an authz plane) still needs
    authorization=True, because an unenforced plane would serve every route unauthenticated."""
    from agno.os.authz.role_store import ManagedRoleStore

    db = SqliteDb(db_file=str(tmp_path / "plane.db"))
    with pytest.raises(ValueError, match="authorization=True"):
        _os(tmp_path, authorization_config=AuthorizationConfig(role_store=ManagedRoleStore(db=db))).get_app()
