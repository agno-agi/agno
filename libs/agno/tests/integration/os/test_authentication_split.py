"""authentication vs authorization: identity is separable from access control.

``authentication=True`` runs the auth middleware in verify-only mode: a valid token is required
and the caller's identity is populated, but no scopes/roles are enforced. So the user directory
and per-user isolation -- which need identity, not access rules -- work without opting into the
whole authorization layer. This is the "user directory without authorization" answer.
"""

import pytest

pytest.importorskip("sqlalchemy")

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS, create_dev_token  # noqa: E402
from agno.os.config import AuthorizationConfig, UserDirectoryConfig  # noqa: E402

SECRET = "authentication-split-secret-at-least-256-bits-xxxxxx"


def _os(tmp_path, **kw):
    return AgentOS(
        id="auth-split-os",
        agents=[Agent(id="research-agent", name="R", db=InMemoryDb())],
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        **kw,
    )


def test_authentication_gives_identity_without_enforcing_access(tmp_path):
    """authentication=True: a valid token is required (identity), the user is provisioned into the
    directory, but scopes are NOT enforced -- an unscoped token can use a route that would need
    agents:read under authorization=True."""
    from fastapi.testclient import TestClient

    os_ = _os(
        tmp_path,
        authentication=True,  # verify who, no access rules
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256"),
        user_directory=UserDirectoryConfig(store=True, auto_provision=True),
    )
    client = TestClient(os_.get_app())

    # identity IS required: no token -> 401
    assert client.get("/agents/research-agent").status_code == 401

    # a valid but UNSCOPED token: allowed (no authz enforcement) AND auto-registered for real
    tok = create_dev_token("alice", secret=SECRET, email="alice@co", name="Alice")
    r = client.get("/agents/research-agent", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text  # would be 403 under authorization=True (no agents:read)
    assert os_.user_directory.store.get("alice") is not None
    assert os_.user_directory.store.get("alice")["email"] == "alice@co"


def test_unauthenticated_run_registers_the_user_as_a_roster(tmp_path):
    """No auth at all: the directory is a plain roster. A run whose user_id is 'chegizkhan'
    (self-asserted, no token) registers that person -- the no-IdP demo path. Construction does
    NOT raise, and the id lands in the directory on the run."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    os_ = _os(tmp_path, user_directory=UserDirectoryConfig(store=True, auto_provision=True))
    client = TestClient(os_.get_app())  # no raise: a directory without auth is a valid roster

    assert os_.user_directory.store.get("chegizkhan") is None

    class MockRunOutput:
        def to_dict(self):
            return {"run_id": "r1"}

    with patch.object(Agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = MockRunOutput()
        r = client.post(
            "/agents/research-agent/runs",
            data={"message": "hi", "stream": "false", "user_id": "chegizkhan"},
        )
    assert r.status_code == 200, r.text
    assert os_.user_directory.store.get("chegizkhan") is not None  # roster populated from the run


def test_no_auth_directory_does_not_enforce_disabled(tmp_path):
    """Without auth the disabled flag is ADVISORY, not a kill-switch: the id is self-asserted, so
    a run is NOT blocked. Enforcement is a property of authentication/authorization."""
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from agno.os.authz.user_store import ManagedUserStore

    store = ManagedUserStore(db=SqliteDb(db_file=str(tmp_path / "dir.db")))
    store.upsert("chegizkhan", name="Chegiz")
    store.set_disabled("chegizkhan", True)

    os_ = _os(tmp_path, user_directory=UserDirectoryConfig(store=store, auto_provision=True))
    client = TestClient(os_.get_app())

    class MockRunOutput:
        def to_dict(self):
            return {"run_id": "r1"}

    with patch.object(Agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = MockRunOutput()
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


def test_authentication_true_requires_a_verification_key(tmp_path):
    """Can't verify identity without a key -> fail fast at construction."""
    with pytest.raises(ValueError, match="requires a JWT verification key"):
        _os(tmp_path, authentication=True, user_directory=True).get_app()


def test_authorization_plane_without_authorization_still_raises(tmp_path):
    """The relaxation is identity-only: a role_store still needs authorization=True, because an
    unenforced plane would serve every route unauthenticated."""
    from agno.os.authz.role_store import ManagedRoleStore

    db = SqliteDb(db_file=str(tmp_path / "plane.db"))
    with pytest.raises(ValueError, match="requires AgentOS.authorization=True"):
        AgentOS(
            id="plane-os",
            agents=[Agent(id="research-agent", name="R", db=InMemoryDb())],
            db=db,
            authentication=True,  # identity on, but a plane needs enforcement (authorization)
            authorization_config=AuthorizationConfig(role_store=ManagedRoleStore(db=db)),
        ).get_app()
