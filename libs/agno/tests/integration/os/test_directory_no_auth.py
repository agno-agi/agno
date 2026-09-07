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
    assert os_.user_directory.store.get("chegizkhan") is None

    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        r = client.post(
            "/agents/research-agent/runs",
            data={"message": "hi", "stream": "false", "user_id": "chegizkhan"},
        )
    assert r.status_code == 200, r.text
    assert os_.user_directory.store.get("chegizkhan") is not None  # roster populated from the run


def test_no_auth_directory_does_not_enforce_disabled(tmp_path):
    """Without auth the disabled flag is ADVISORY, not a kill-switch: the id is self-asserted, so
    a run is NOT blocked. Enforcement is a property of authorization."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from agno.os.authz.user_store import ManagedUserStore

    store = ManagedUserStore(db=SqliteDb(db_file=str(tmp_path / "dir.db")))
    store.upsert("chegizkhan", name="Chegiz")
    store.set_disabled("chegizkhan", True)

    os_ = _os(tmp_path, user_directory=UserDirectoryConfig(store=store, auto_provision=True))
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
    provisioned/enforced, so sync_directory_from_run is a no-op on authenticated requests."""
    from agno.os.middleware.user_scope import sync_directory_from_run

    class _State:
        authenticated = True

    class _App:
        state = type("S", (), {"user_store": object(), "user_auto_provision": True})()

    class _Req:
        state = _State()
        app = _App()

    # Would raise if it tried to use the bogus user_store; the authenticated short-circuit
    # returns before touching it.
    sync_directory_from_run(_Req(), "someone")


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


def test_role_store_still_requires_authorization(tmp_path):
    """Unchanged by the directory/isolation relaxation: a role_store (an authz plane) still needs
    authorization=True, because an unenforced plane would serve every route unauthenticated."""
    from agno.os.authz.role_store import ManagedRoleStore

    db = SqliteDb(db_file=str(tmp_path / "plane.db"))
    with pytest.raises(ValueError, match="authorization=True"):
        _os(tmp_path, authorization_config=AuthorizationConfig(role_store=ManagedRoleStore(db=db))).get_app()
