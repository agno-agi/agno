"""The admin scope's namespace is reserved: no other scope may use it, and no policy row under it
may ever read back as ``agent_os:admin``.

``agent_os:*:admin`` used to parse as resource ``agent_os/*`` + action ``admin`` (a row that grants
nothing), then render back as ``agent_os:admin``. An admin editing that role through the UI or
API and saving the displayed scopes turned a no-op grant into full admin, and the audit trail had
already shown it as admin.
"""

import pytest

pytest.importorskip("sqlalchemy")

from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os.authz import RoleStore  # noqa: E402
from agno.os.authz._scope_policy import ADMIN_SCOPE, resource_action_to_scope, scope_to_resource_action  # noqa: E402


def test_only_the_admin_scope_lives_in_the_agent_os_namespace():
    assert scope_to_resource_action(ADMIN_SCOPE) == ("*", "*")
    for spelling in ("agent_os:*:admin", "agent_os:x:admin", "agent_os:read", "agent_os:*:read"):
        with pytest.raises(ValueError, match="not a resource type"):
            scope_to_resource_action(spelling)


def test_a_row_under_the_admin_namespace_never_renders_as_admin():
    assert resource_action_to_scope("*", "*") == ADMIN_SCOPE
    assert resource_action_to_scope("agent_os/*", "admin") == "agent_os:*:admin"  # honest, and unsaveable
    assert resource_action_to_scope("agent_os/x", "admin") == "agent_os:x:admin"


def test_round_trip_cannot_promote_a_legacy_row_to_admin(tmp_path):
    """A pre-existing ``agent_os/*`` + ``admin`` row (written before the parser refused it) reads
    back as the three-part form, still grants nothing, and re-saving what the UI shows raises
    instead of escalating."""
    db = SqliteDb(db_file=str(tmp_path / "legacy.db"))
    store = RoleStore(db=db)
    with pytest.raises(ValueError):
        store.set_role_scopes("ops", ["agent_os:*:admin"])  # refused on save now
    db.upsert_authz_policy(role="ops", resource="agent_os/*", action="admin", effect="allow")  # legacy row
    entries = store.get_role_scope_entries("ops")
    assert entries == [{"scope": "agent_os:*:admin", "effect": "allow"}]
    assert store._engine.check_scope(ADMIN_SCOPE, roles=["ops"]) is False
    with pytest.raises(ValueError):
        store.set_role_scopes("ops", entries)  # the edit-and-save that used to escalate
    assert store._engine.check_scope(ADMIN_SCOPE, roles=["ops"]) is False
