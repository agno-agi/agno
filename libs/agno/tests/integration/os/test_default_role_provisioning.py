"""Default-role-on-provision.

When a user is auto-provisioned (JIT) under managed roles, they are granted the default
role so they land usable rather than inert. Single-role model (a subject holds one role):
the default is the role flagged ``is_default`` in the role store, or the explicit
``UserDirectoryConfig.default_role`` override. If neither resolves the user is left inert
and a warning is logged, never a silent grant. These exercise the shared choke-point helper
(``provision_user_with_default_role``) and the role-store plumbing it relies on.
"""

import os
import tempfile

import pytest

pytest.importorskip("sqlalchemy")  # managed roles persist/enforce via the native engine + SQLAlchemy

from agno.os.auth import provision_user_with_default_role  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.authz.user_store import ManagedUserStore  # noqa: E402


def _db_url() -> str:
    fd, path = tempfile.mkstemp(suffix=".authz.db")
    os.close(fd)
    return f"sqlite:///{path}"


def _roles() -> ManagedRoleStore:
    return ManagedRoleStore(db_url=_db_url())


def _users() -> ManagedUserStore:
    return ManagedUserStore(db_url=_db_url())


# ------------------------------------------------ role store: default_role + uniqueness
def test_default_role_returns_the_flagged_role():
    roles = _roles()
    roles.set_role_scopes("member", ["agents:*:read"], is_default=True)
    roles.set_role_scopes("admin", ["agent_os:admin"])
    assert roles.default_role() == "member"


def test_default_role_is_none_when_nothing_flagged():
    roles = _roles()
    roles.set_role_scopes("member", ["agents:*:read"])
    assert roles.default_role() is None


def test_is_default_is_unique_setting_a_new_default_clears_the_old():
    """Single-default model: only one role may carry is_default, so default_role() is
    unambiguous. Flagging a second role clears the first."""
    roles = _roles()
    roles.set_role_scopes("member", ["agents:*:read"], is_default=True)
    roles.set_role_scopes("staff", ["agents:*:read"], is_default=True)
    assert roles.default_role() == "staff"
    flags = {r["slug"]: r["is_default"] for r in roles.list_roles_detailed()}
    assert flags["staff"] is True
    assert flags["member"] is False


# ------------------------------------------------ provision_user_with_default_role
def test_new_user_gets_the_is_default_role():
    roles, users = _roles(), _users()
    roles.set_role_scopes("member", ["agents:*:read"], is_default=True)
    user = provision_user_with_default_role(users, roles, None, "alice", {"email": "a@co", "name": "A"})
    assert user["email"] == "a@co"
    assert roles.roles_of("alice") == ["member"]


def test_config_default_role_overrides_is_default():
    roles, users = _roles(), _users()
    roles.set_role_scopes("member", ["agents:*:read"], is_default=True)
    roles.set_role_scopes("power", ["agents:*:read", "agents:*:write"])
    # explicit UserDirectoryConfig.default_role wins over the is_default flag
    provision_user_with_default_role(users, roles, "power", "bob", {"email": "b@co"})
    assert roles.roles_of("bob") == ["power"]


def test_existing_user_is_not_regranted_on_later_login():
    """The grant happens only on first creation, so a later login never re-grants and never
    fights an admin who removed the role."""
    roles, users = _roles(), _users()
    roles.set_role_scopes("member", ["agents:*:read"], is_default=True)
    # first login: provisioned + granted the default role
    provision_user_with_default_role(users, roles, None, "carol", {"email": "c@co"})
    assert roles.roles_of("carol") == ["member"]
    # admin revokes; a subsequent login must NOT silently re-grant (created=False)
    roles.unassign("carol", "member")
    provision_user_with_default_role(users, roles, None, "carol", {"email": "c@co"})
    assert roles.roles_of("carol") == []


def test_no_default_leaves_user_inert_and_warns(monkeypatch):
    roles, users = _roles(), _users()
    roles.set_role_scopes("member", ["agents:*:read"])  # exists, but not flagged default
    warnings: list[str] = []
    monkeypatch.setattr("agno.os.auth.log_warning", lambda msg: warnings.append(msg))
    provision_user_with_default_role(users, roles, None, "dave", {"email": "d@co"})
    # user exists (provisioned) but holds no role: inert until an admin assigns one
    assert users.get("dave") is not None
    assert roles.roles_of("dave") == []
    assert any("no default role" in w for w in warnings)


def test_no_role_store_is_a_noop_no_grant_no_warn(monkeypatch):
    """Under the scope plane (no role store) roles do not apply: provision only, no grant,
    no warning."""
    users = _users()
    warnings: list[str] = []
    monkeypatch.setattr("agno.os.auth.log_warning", lambda msg: warnings.append(msg))
    user = provision_user_with_default_role(users, None, None, "erin", {"email": "e@co"})
    assert user["email"] == "e@co"
    assert users.get("erin") is not None
    assert warnings == []
