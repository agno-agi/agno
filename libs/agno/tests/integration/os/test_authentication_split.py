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


def test_directory_without_any_auth_is_still_refused(tmp_path):
    """The directory needs SOME verified identity; with neither authentication nor authorization
    it raises (nothing to key off, kill-switch can't run)."""
    with pytest.raises(ValueError, match="needs a verified identity"):
        _os(tmp_path, user_directory=True).get_app()


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
