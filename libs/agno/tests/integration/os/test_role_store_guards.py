"""The role store refuses the changes that lock admins out or over-grant silently.

- A deny on ``agent_os:admin`` (deny overrides, and a boot-time define_role preserves it, so
  the lockout survived restarts).
- Removing the last stored admin: revoking their role, deleting the role, rewriting its scopes
  without admin, or moving the holder to a non-admin role.
- Flagging an admin-conferring role as the default (every provisioned user becomes admin).
- Naming a role after an existing user, or assigning a user id as a role (subjects and roles
  share one namespace, so either turns assignments into inheritance).
- ``delete_role`` now drops the role's own inheritance edges, so a later subject named like a
  deleted role cannot inherit through them.
"""

import time

import jwt
import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import Authorization, UserDirectory  # noqa: E402
from agno.os.authz._role_store import RoleChangeRefused, RoleStore  # noqa: E402
from agno.os.authz.engine import EngineAuthorizationProvider  # noqa: E402
from agno.os.authz.provider import AuthorizationContext  # noqa: E402

SECRET = "role-guards-secret-at-least-32-bytes-long!!"
OS_ID = "role-guards-os"


@pytest.fixture
def store(tmp_path):
    s = RoleStore(db=SqliteDb(db_file=str(tmp_path / "guards.db")))
    s.set_role_scopes("admin", ["agent_os:admin"])
    s.set_role_scopes("viewer", ["agents:*:read"])
    s.assign("root", "admin")
    return s


# --------------------------------------------------------------------------- deny on admin


def test_a_deny_on_the_admin_scope_is_refused(store):
    with pytest.raises(ValueError, match="deny on 'agent_os:admin'"):
        store.set_role_scopes("admin", [("agent_os:admin", "deny")])
    with pytest.raises(ValueError, match="deny on 'agent_os:admin'"):
        store.patch_role_scopes("admin", upsert=[{"scope": "agent_os:admin", "effect": "deny"}])
    assert store.can_manage("root")


# --------------------------------------------------------------------------- last admin


def test_the_last_admin_cannot_be_revoked_demoted_or_have_the_role_removed(store):
    with pytest.raises(RoleChangeRefused):
        store.unassign("root", "admin")
    with pytest.raises(RoleChangeRefused):
        store.assign("root", "viewer")
    with pytest.raises(RoleChangeRefused):
        store.remove_role("admin")
    with pytest.raises(RoleChangeRefused):
        store.set_role_scopes("admin", ["agents:*:read"])
    with pytest.raises(RoleChangeRefused):
        store.patch_role_scopes("admin", remove=["agent_os:admin"])
    assert store.admin_subjects() == ["root"]


def test_a_handover_is_allowed_once_someone_else_is_admin(store):
    store.assign("carol", "admin")
    store.assign("root", "viewer")  # root demoted: carol still administers
    assert store.admin_subjects() == ["carol"]
    assert store.roles_of("root") == ["viewer"]


def test_unassign_of_the_last_admin_is_refused_after_a_handover(store):
    store.assign("carol", "admin")
    store.assign("root", "viewer")
    with pytest.raises(RoleChangeRefused):
        store.unassign("carol", "admin")


def test_non_admin_changes_are_never_blocked(store):
    store.assign("dave", "viewer")
    store.unassign("dave", "viewer")
    store.set_role_scopes("viewer", ["agents:*:run"])
    store.remove_role("viewer")
    assert store.admin_subjects() == ["root"]


def test_guard_is_off_when_admins_live_on_the_token(tmp_path):
    """With a roles_claim, admin comes from the IdP: an empty stored admin set is not a lockout."""
    authz = Authorization(db=SqliteDb(db_file=str(tmp_path / "claim.db")), roles_claim="roles")
    authz.define_role("admin", ["agent_os:admin"])
    authz.set_role("root", "admin")
    authz.unassign("root", "admin")  # not refused
    assert authz.admin_subjects() == []


def test_guard_is_off_under_trust_token_scopes(tmp_path):
    authz = Authorization(db=SqliteDb(db_file=str(tmp_path / "tts.db")), trust_token_scopes=True)
    authz.define_role("admin", ["agent_os:admin"])
    authz.set_role("root", "admin")
    authz.unassign("root", "admin")  # not refused
    assert authz.admin_subjects() == []


def test_a_locked_out_store_is_not_blocked_from_recovering(tmp_path):
    """The guard only bites while someone holds admin: a fresh or already locked-out store must
    let the bootstrap (and any repair) through."""
    s = RoleStore(db=SqliteDb(db_file=str(tmp_path / "fresh.db")))
    s.set_role_scopes("admin", ["agent_os:admin"])
    s.set_role_scopes("viewer", ["agents:*:read"])
    s.assign("someone", "viewer")  # nobody is admin; must not raise
    s.unassign("someone", "viewer")
    s.assign("root", "admin")
    assert s.admin_subjects() == ["root"]


# --------------------------------------------------------------------------- admin default


def test_an_admin_role_cannot_be_the_default(store):
    with pytest.raises(RoleChangeRefused, match="cannot be the default"):
        store.set_role_meta("admin", is_default=True)
    with pytest.raises(RoleChangeRefused, match="cannot be the default"):
        store.set_role_scopes("ops", ["agent_os:admin"], is_default=True)
    # And admin cannot be written onto the current default role.
    store.set_role_meta("viewer", is_default=True)
    with pytest.raises(RoleChangeRefused, match="cannot be the default"):
        store.set_role_scopes("viewer", ["agent_os:admin"])
    with pytest.raises(RoleChangeRefused, match="cannot be the default"):
        store.patch_role_scopes("viewer", upsert=["agent_os:admin"])
    assert store.default_role() == "viewer"
    assert not store._engine.check_scope("agent_os:admin", roles=["viewer"])


def test_define_role_default_true_on_an_admin_role_is_refused_at_boot(tmp_path):
    authz = Authorization(db=SqliteDb(db_file=str(tmp_path / "boot.db")))
    with pytest.raises(RoleChangeRefused):
        authz.define_role("admin", ["agent_os:admin"], default=True)


# --------------------------------------------------------------------------- namespace


def test_a_role_cannot_be_named_after_a_user_with_an_assignment(store):
    store.assign("ops", "viewer")
    with pytest.raises(RoleChangeRefused, match="existing user id"):
        store.create_role("ops")
    with pytest.raises(RoleChangeRefused, match="existing user id"):
        store.set_role_scopes("ops", ["agents:*:read"])
    with pytest.raises(RoleChangeRefused, match="existing user id"):
        store.patch_role_scopes("ops", upsert=["agents:*:read"])
    assert "ops" not in store.list_roles()


def test_a_role_cannot_be_named_after_a_directory_user(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "dir.db"))
    users = UserDirectory(db=db)
    users.upsert("erin")
    s = RoleStore(db=db)
    with pytest.raises(RoleChangeRefused, match="existing user id"):
        s.create_role("erin")


def test_a_user_id_cannot_be_assigned_as_a_role(store):
    store.assign("bob", "viewer")
    with pytest.raises(RoleChangeRefused, match="is a user, not a role"):
        store.assign("alice", "bob")
    # bob is untouched and still resolves.
    provider = EngineAuthorizationProvider(store._engine)
    assert provider.check(
        AuthorizationContext(principal_id="bob", resource_type="agents", resource_id="x", action="read")
    )


def test_delete_role_drops_its_own_inheritance_edges(store):
    store.set_role_scopes("senior", ["agents:*:run"])
    store._engine.assign("senior", "viewer")  # senior inherits viewer (an inheritance edge)
    store.remove_role("senior")
    provider = EngineAuthorizationProvider(store._engine)
    # A later subject named "senior" (no assignment) must not inherit viewer through a leftover edge.
    assert not provider.check(
        AuthorizationContext(principal_id="senior", resource_type="agents", resource_id="x", action="read")
    )
    assert store._engine.roles_of("senior") == []


# --------------------------------------------------------------------------- async twins


@pytest.mark.asyncio
async def test_async_twins_apply_the_same_guards(tmp_path):
    s = RoleStore(db=SqliteDb(db_file=str(tmp_path / "async.db")))
    await s.aset_role_scopes("admin", ["agent_os:admin"])
    await s.aset_role_scopes("viewer", ["agents:*:read"])
    await s.aassign("root", "admin")
    await s.aassign("ops", "viewer")
    with pytest.raises(RoleChangeRefused):
        await s.aunassign("root", "admin")
    with pytest.raises(RoleChangeRefused):
        await s.aassign("root", "viewer")
    with pytest.raises(RoleChangeRefused):
        await s.aremove_role("admin")
    with pytest.raises(RoleChangeRefused):
        await s.aset_role_scopes("admin", ["agents:*:read"])
    with pytest.raises(RoleChangeRefused):
        await s.apatch_role_scopes("admin", remove=["agent_os:admin"])
    with pytest.raises(RoleChangeRefused):
        await s.aset_role_meta("admin", is_default=True)
    with pytest.raises(RoleChangeRefused):
        await s.acreate_role("ops")
    with pytest.raises(RoleChangeRefused):
        await s.aassign("alice", "ops")
    with pytest.raises(ValueError, match="deny on 'agent_os:admin'"):
        await s.aset_role_scopes("admin", [("agent_os:admin", "deny")])
    assert await s.aadmin_subjects() == ["root"]


# --------------------------------------------------------------------------- the admin API


def _token(sub, scopes=None):
    payload = {"sub": sub, "aud": OS_ID, "exp": int(time.time()) + 3600}
    if scopes is not None:
        payload["scopes"] = scopes
    return {"Authorization": f"Bearer {jwt.encode(payload, SECRET, algorithm='HS256')}"}


@pytest.fixture
def api(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "api.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], audience=OS_ID, algorithm="HS256")
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    authz.seed(admin="root")
    agent_os = AgentOS(
        id=OS_ID, db=db, agents=[Agent(id="a", db=InMemoryDb())], authorization=authz, user_directory=True
    )
    return TestClient(agent_os.get_app())


def test_the_api_answers_409_for_a_refused_change(api):
    root = _token("root")
    r = api.delete("/authz/subjects/root/roles/admin", headers=root)
    assert r.status_code == 409 and "no subject holding" in r.json()["detail"]
    r = api.delete("/authz/roles/admin", headers=root)
    assert r.status_code == 409
    r = api.patch("/authz/roles/admin", json={"is_default": True}, headers=root)
    assert r.status_code == 409 and "cannot be the default" in r.json()["detail"]
    r = api.post("/authz/subjects/root/roles", json={"role": "viewer"}, headers=root)
    assert r.status_code == 409
    # Still an admin afterwards.
    assert api.get("/authz/subjects/root/roles", headers=root).json()["role"] == "admin"


def test_the_api_answers_422_for_a_deny_on_admin(api):
    root = _token("root")
    r = api.patch(
        "/authz/roles/admin/scopes",
        json={"upsert": [{"scope": "agent_os:admin", "effect": "deny"}]},
        headers=root,
    )
    assert r.status_code == 422 and "deny on 'agent_os:admin'" in r.json()["detail"]


def test_deleting_the_last_admin_user_is_refused(api):
    root = _token("root")
    assert api.post("/users", json={"id": "root"}, headers=root).status_code == 200
    r = api.delete("/users/root", headers=root)
    assert r.status_code == 409
    assert api.get("/authz/subjects/root/roles", headers=root).json()["role"] == "admin"


def test_the_api_still_works_for_ordinary_changes(api):
    root = _token("root")
    assert api.post("/authz/roles", json={"slug": "runner"}, headers=root).status_code == 201
    assert api.put("/authz/roles/runner/scopes", json={"scopes": ["agents:*:run"]}, headers=root).status_code == 200
    assert api.post("/authz/subjects/dave/roles", json={"role": "runner"}, headers=root).status_code == 200
    assert api.delete("/authz/subjects/dave/roles/runner", headers=root).status_code == 200
    assert api.delete("/authz/roles/runner", headers=root).status_code == 200
    assert api.get("/authz/audit", headers=root).status_code in (200, 404)
