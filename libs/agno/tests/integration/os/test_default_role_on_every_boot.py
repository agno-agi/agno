"""The default role is a provisioning policy, so ``define_role(..., default=True)`` applies on every
boot, not only when the role is first created. Scopes stay bootstrap-only. And the directory names
where ``default_role`` went instead of failing with a bare TypeError.
"""

import pytest

pytest.importorskip("sqlalchemy")

from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os.authz import Authorization, UserDirectory  # noqa: E402

SECRET = "default-role-boot-secret-at-least-256-bits-long-xxxxxx"


def _boot(db, *, default: str):
    """One boot of the app's role definitions, with ``default`` as the default role."""
    authz = Authorization(db=db, verification_keys=[SECRET], audience="dr-os")
    authz.define_role("viewer", ["agents:*:read"], default=(default == "viewer"))
    authz.define_role("member", ["agents:*:read", "agents:*:run"], default=(default == "member"))
    return authz.role_store


def test_moving_the_default_in_code_takes_effect_on_the_next_boot(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    store = _boot(db, default="viewer")
    assert store.default_role() == "viewer"

    # the code now says member is the default; both roles already exist with scopes
    store = _boot(db, default="member")
    assert store.default_role() == "member"
    assert store.get_role("viewer")["is_default"] is False  # one default at a time

    # and back again
    assert _boot(db, default="viewer").default_role() == "viewer"


def test_scopes_stay_bootstrap_only_while_the_default_moves(tmp_path):
    """An admin's runtime scope edit survives a reboot that also moves the default."""
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    store = _boot(db, default="viewer")
    store.set_role_scopes("member", ["agents:*:read"])  # admin narrows member at runtime

    store = _boot(db, default="member")  # boot code still lists agents:*:run for member
    assert store.get_role_scopes("member") == ["agents:read"]  # the edit is kept (canonical form)
    assert store.default_role() == "member"  # the default moved


def test_omitting_default_never_clears_an_existing_one(tmp_path):
    """Code can assert a default but not un-assert one by omission; that is for the admin API."""
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    _boot(db, default="viewer")
    store = _boot(db, default="none")  # neither role says default=True
    assert store.default_role() == "viewer"


def test_a_default_role_set_in_the_admin_api_is_overridden_by_code(tmp_path):
    """The IdP-style deployment where code owns the default: an admin flip is undone on the next boot.
    Documented on define_role, so this pins the rule rather than leaving it to chance."""
    db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    store = _boot(db, default="viewer")
    store.set_role_meta("member", is_default=True)  # what PATCH /authz/roles/member does
    assert store.default_role() == "member"
    assert _boot(db, default="viewer").default_role() == "viewer"


def test_user_directory_points_default_role_at_define_role():
    with pytest.raises(TypeError, match="define_role\\(slug, scopes, default=True\\)"):
        UserDirectory(auto_provision=True, default_role="viewer")  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected keyword argument\\(s\\): nope"):
        UserDirectory(nope=1)  # type: ignore[call-arg]
