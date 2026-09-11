"""The Authorization facade: one object for verification + roles + users + audit + admin API.

Covers the shapes the DX review asked for: a verify-only one-liner (no roles), managed roles wired
end to end through a served AgentOS (eager db and borrowed db), idempotent seeding, the auto-mounted
admin API, and the trust_token_scopes composite. The facade is a convenience layer over the same
primitives, so these assert behavior parity with the hand-assembled setup.
"""

import logging
import time

import pytest

pytest.importorskip("sqlalchemy")

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import Authorization, ManagedUserStore  # noqa: E402
from agno.os.config import UserDirectoryConfig  # noqa: E402

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
    """The documented verify-only one-liner (no roles) builds NO role store: provider falls back to
    scope RBAC. This is what an isolation / scope-based deployment writes, and it must not silently
    stand up a role store."""
    db = SqliteDb(db_file=str(tmp_path / "vo.db"))
    authz = Authorization(verification_keys=[SECRET], audience=OS_ID)  # the exact documented shape
    authz._bind(db)
    assert authz.role_store is None
    assert authz.provider is None  # AgentOS defaults to ScopeAuthorizationProvider
    cfg = authz.authorization_config()
    assert cfg.verification_keys == [SECRET] and cfg.audience == OS_ID


def test_user_directory_is_not_on_the_authorization_object(tmp_path):
    """The directory is a top-level AgentOS(user_directory=...) concern, a peer of user_isolation, NOT
    configured on Authorization. So Authorization has no user_directory/auto_provision params, and the
    directory store is read from AgentOS, not the facade."""
    import inspect

    from agno.os.authz.user_store import ManagedUserStore
    from agno.os.config import UserDirectoryConfig

    params = inspect.signature(Authorization.__init__).parameters
    assert "user_directory" not in params  # moved out to AgentOS
    assert "auto_provision" not in params  # a directory concern, on UserDirectoryConfig now

    db = SqliteDb(db_file=str(tmp_path / "onedir.db"))
    store = ManagedUserStore(db=db)
    authz = Authorization(db=db, verification_keys=[SECRET], audience=OS_ID)
    authz.define_role("viewer", ["agents:*:read"])
    os_ = AgentOS(
        id=OS_ID, db=db, agents=_agents(), authorization=authz, user_directory=UserDirectoryConfig(user_store=store)
    )
    assert os_.user_directory.user_store is store  # your store is used, configured on AgentOS


def test_borrowed_db_applies_buffered_definitions(tmp_path):
    """No db passed to Authorization: role definitions buffer, then apply when the OS db binds
    (the 'never pass db twice' path). The directory is a separate top-level store."""
    authz = Authorization(audit=True, verification_keys=[SECRET], audience=OS_ID)
    authz.define_role("runner", ["agents:*:run"])
    assert authz._bound is False

    db = SqliteDb(db_file=str(tmp_path / "borrow.db"))
    users = ManagedUserStore(db=db)
    users.upsert("carol", email="c@co")  # directory row, seeded on the store directly
    os_ = AgentOS(
        id=OS_ID,
        db=db,
        agents=_agents(),
        user_directory=UserDirectoryConfig(user_store=users),
        authorization=authz,
    )
    os_.get_app()  # binds the facade -> buffered role defs apply
    authz.role_store.assign("carol", "runner")  # role assigned through the now-bound store
    assert authz.role_store.list_roles() == ["runner"]
    assert authz.role_store.roles_of("carol") == ["runner"]
    assert os_.user_directory.user_store.get("carol") is not None


def test_seed_is_idempotent(tmp_path):
    """Seeding on every start is safe: the admin seed and single-role assigns are no-ops when
    unchanged, so a restart neither re-grants nor duplicates."""
    db = SqliteDb(db_file=str(tmp_path / "seed.db"))
    authz = Authorization(db=db)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    authz.seed(admin="root")
    authz.seed(admin="root")  # again -> no-op
    authz.role_store.assign("bob", "viewer")
    authz.role_store.assign("bob", "viewer")  # again -> no-op
    assert authz.role_store.roles_of("root") == ["admin"]
    assert authz.role_store.roles_of("bob") == ["viewer"]
    assert authz.role_store.default_role() == "viewer"


def test_reboot_preserves_runtime_operator_edits(tmp_path):
    """The bootstrap must never clobber runtime edits. Define + seed, promote a user and widen a role
    through the store (what the admin API does), then re-run the identical boot sequence (a restart).
    Both edits survive -- the 'safe to run on every start' claim must actually hold."""
    dbfile = str(tmp_path / "reboot.db")

    def boot():
        a = Authorization(db=SqliteDb(db_file=dbfile))
        a.define_role("viewer", ["agents:*:read"], default=True)
        a.define_role("runner", ["agents:*:read", "agents:*:run"])
        if not a.role_store.roles_of("bob"):  # bootstrap: assign only if new, so a promotion survives
            a.role_store.assign("bob", "viewer")
        return a

    a1 = boot()
    assert a1.role_store.roles_of("bob") == ["viewer"]
    # operator edits at runtime, through the store (the /authz admin API path)
    a1.role_store.assign("bob", "runner")  # promote bob
    a1.role_store.set_role_scopes("viewer", ["agents:*:read", "agents:*:run"])  # widen viewer

    a2 = boot()  # a restart re-runs define_role + seed on the same db
    assert a2.role_store.roles_of("bob") == ["runner"]  # promotion survived
    assert "agents:run" in a2.role_store.get_role_scopes("viewer")  # widened scope survived


def test_seed_admin_role_configurable_and_warns_when_missing(tmp_path):
    """seed(admin=) must not hardcode 'admin': admin_role is configurable, and seeding an admin whose
    role does not grant agent_os:admin warns instead of silently leaving can_manage False."""
    db = SqliteDb(db_file=str(tmp_path / "admin.db"))
    authz = Authorization(db=db)
    authz.define_role("superuser", ["agent_os:admin"])
    authz.seed(admin="alice", admin_role="superuser")
    assert authz.role_store.can_manage("alice") is True  # custom admin role confers admin

    authz.seed(admin="bob")  # default admin_role "admin" was never defined
    assert authz.role_store.can_manage("bob") is False

    # The mismatch is warned at finalize (authorization_config), so order of define_role vs seed
    # cannot cause a false positive. Capture the agno logger directly (propagate=False).
    messages: list = []

    class _Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = _Capture()
    handler.setLevel(logging.WARNING)  # ignore INFO decision logs
    logging.getLogger("agno").addHandler(handler)
    try:
        authz.authorization_config()  # AgentOS calls this once, after all setup
    finally:
        logging.getLogger("agno").removeHandler(handler)
    assert any("agent_os:admin" in m and "bob" in m for m in messages)  # warned, not silent
    assert not any("alice" in m for m in messages)  # alice's real admin role is not flagged


def test_seed_admin_warning_survives_define_after_seed_order(tmp_path):
    """The admin warning must not depend on call order: defining the admin role AFTER seeding it must
    NOT warn (the deferred finalize sees the final state)."""
    messages: list = []

    class _Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    db = SqliteDb(db_file=str(tmp_path / "order.db"))
    authz = Authorization(db=db)
    authz.seed(admin="alice", admin_role="boss")  # seed first
    authz.define_role("boss", ["agent_os:admin"])  # define after
    handler = _Capture()
    handler.setLevel(logging.WARNING)  # ignore INFO decision logs
    logging.getLogger("agno").addHandler(handler)
    try:
        authz.authorization_config()
    finally:
        logging.getLogger("agno").removeHandler(handler)
    assert authz.role_store.can_manage("alice") is True
    assert not messages  # no false-positive warning despite seed-before-define


def test_facade_setup_rejects_async_db(tmp_path):
    """define_role/seed write synchronously; against an async db they raise a clear facade-level error
    instead of a confusing 'use the async variant' failure deep in the engine."""
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    authz = Authorization(db=AsyncSqliteDb(db_file=str(tmp_path / "a.db")))
    with pytest.raises(ValueError, match="synchronous database"):
        authz.define_role("viewer", ["agents:*:read"])


def test_facade_async_os_db_setup_raises_at_agentos(tmp_path):
    """Borrowing an async OS db: the buffered define_role surfaces the same clear error when AgentOS
    binds, not a deep engine error."""
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    authz = Authorization()  # borrow the OS db
    authz.define_role("viewer", ["agents:*:read"])  # buffered until bind
    with pytest.raises(ValueError, match="synchronous database"):
        AgentOS(id=OS_ID, db=AsyncSqliteDb(db_file=str(tmp_path / "os.db")), agents=_agents(), authorization=authz)


def test_facade_prebuilt_async_store_no_setup_ok(tmp_path):
    """A facade with a pre-configured async store and NO define_role/seed works against an async db:
    only the sync setup writes are refused, not the provider wiring / request-time path."""
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb
    from agno.os.authz.role_store import ManagedRoleStore

    adb = AsyncSqliteDb(db_file=str(tmp_path / "a.db"))
    authz = Authorization(role_store=ManagedRoleStore(db=adb), verification_keys=[SECRET], audience=OS_ID)
    authz._bind(adb)
    authz.authorization_config()  # no writes
    assert authz.provider is not None  # just wires the provider


def test_agentos_rejects_config_alongside_facade(tmp_path):
    """Passing authorization_config / audit alongside an Authorization facade is a silent-preference
    footgun (a data split if the facade has its own db), so AgentOS rejects those. (user_directory is
    NOT rejected: it is a top-level concern the facade does not own.)"""
    db = SqliteDb(db_file=str(tmp_path / "conflict.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], audience=OS_ID)
    authz.define_role("admin", ["agent_os:admin"])
    with pytest.raises(ValueError, match="already owns"):
        AgentOS(id=OS_ID, db=db, agents=_agents(), authorization=authz, audit=True)


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
    )
    authz = Authorization(**kwargs) if borrow_db else Authorization(db=db, **kwargs)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    authz.define_role("runner", ["agents:research:read", "agents:research:run"])
    authz.seed(admin="root")  # admin ROLE only
    # The directory is a separate top-level store, a peer of user_isolation; seed rows on it directly.
    # Include the admin: with auto_provision + a default role, a subject not in the directory is
    # provisioned to the default role on first request, which would demote the seeded admin.
    users = ManagedUserStore(db=db)
    users.upsert("root", name="Bootstrap admin")
    users.upsert("bob", email="bob@co", name="Bob")
    users.upsert("carol")
    os_ = AgentOS(
        id=OS_ID,
        db=db,
        agents=_agents(),
        user_directory=UserDirectoryConfig(user_store=users, auto_provision=True),
        authorization=authz,
    )
    # AgentOS bound the facade's role store; assign the seeded users their roles through it.
    authz.role_store.assign("bob", "viewer")
    authz.role_store.assign("carol", "runner")
    return os_


@pytest.mark.parametrize("borrow_db", [True, False], ids=["borrowed-db", "own-db"])
def test_served_facade_enforces_roles(tmp_path, borrow_db):
    """Managed roles enforce end to end through a served AgentOS built from the facade, whether the
    facade borrows the OS db or holds its own."""
    from unittest.mock import AsyncMock, patch

    client = TestClient(_served(tmp_path, borrow_db=borrow_db).get_app())
    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()

        def run(sub, agent):
            return client.post(
                f"/agents/{agent}/runs", headers=_auth(sub), data={"message": "hi", "stream": "false"}
            ).status_code

        assert run("carol", "secret") == 403  # runner has no secret grant
        assert run("carol", "research") == 200  # runner may run research
        assert run("root", "secret") == 200  # admin role bypass
        assert run("nobody", "research") == 403  # default role is viewer (read only), so a run is denied
        # ...but the unknown caller WAS JIT-provisioned with the default role, so a read is allowed
        # (an ungranted caller would be 403 here too) -- this is what proves the default grant fired.
        assert client.get("/agents/research", headers=_auth("nobody")).status_code == 200


def test_authorization_config_is_deprecated_not_a_second_spelling(tmp_path):
    """AuthorizationConfig has one remaining job: keep deployments written against the released
    field set booting. authorization_config= still works with authorization=True and warns once;
    authorization=AuthorizationConfig(...) is refused rather than becoming a new spelling of a
    deprecated type."""
    from agno.os.config import AuthorizationConfig

    cfg = AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    messages: list = []

    class _Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = _Capture()
    handler.setLevel(logging.WARNING)
    logging.getLogger("agno").addHandler(handler)
    try:
        os_ = AgentOS(
            id=OS_ID,
            db=SqliteDb(db_file=str(tmp_path / "cfg.db")),
            agents=_agents(),
            authorization=True,
            authorization_config=cfg,
        )
    finally:
        logging.getLogger("agno").removeHandler(handler)
    assert os_.authorization is True and os_.authorization_config is cfg  # still honoured
    assert any("authorization_config" in m and "deprecated" in m for m in messages)

    with pytest.raises(TypeError, match="authorization_config="):
        AgentOS(id=OS_ID, db=SqliteDb(db_file=str(tmp_path / "cfg2.db")), agents=_agents(), authorization=cfg)


def test_directory_is_explicit_top_level_never_inferred_from_roles(tmp_path):
    """The directory is a top-level AgentOS(user_directory=...) concern, never inferred from roles. A
    roles-only deployment gets no directory and no /users; adding user_directory=True gives both.
    Authorization no longer seeds users at all: seeding is on the ManagedUserStore, and seed(users=...)
    is rejected."""
    # Roles only, no top-level directory -> role store, but no directory and no /users.
    roles_only = Authorization(
        db=SqliteDb(db_file=str(tmp_path / "explicit.db")),
        verification_keys=[SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
    )
    roles_only.define_role("admin", ["agent_os:admin"])
    roles_only.seed(admin="root")  # an admin role, but no users= -> no directory
    os_ro = AgentOS(id=OS_ID, db=roles_only._db, agents=_agents(), authorization=roles_only)
    assert roles_only.role_store is not None
    assert os_ro.user_directory is None  # roles do not imply a directory
    client = TestClient(os_ro.get_app())
    assert client.get("/authz/roles", headers=_auth("root")).status_code == 200
    assert client.get("/users", headers=_auth("root")).status_code == 404  # no directory -> no /users

    # roles_claim alone puts roles in play, and still stands up no directory.
    idp = Authorization(
        db=SqliteDb(db_file=str(tmp_path / "idp.db")), verification_keys=[SECRET], audience=OS_ID, roles_claim="role"
    )
    assert idp.role_store is not None

    # Ask for the directory top-level -> it exists and /users mounts (under auth). People are seeded on
    # the store; Authorization only bootstraps the admin role.
    adb = SqliteDb(db_file=str(tmp_path / "asked.db"))
    store = ManagedUserStore(db=adb)
    store.upsert("bob", email="bob@co")
    asked = Authorization(verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    asked.define_role("admin", ["agent_os:admin"])
    asked.seed(admin="root")
    os_asked = AgentOS(
        id=OS_ID,
        db=adb,
        agents=_agents(),
        user_directory=UserDirectoryConfig(user_store=store),
        authorization=asked,
    )
    client2 = TestClient(os_asked.get_app())
    assert os_asked.user_directory.user_store.get("bob") is not None  # the seeded person is in the directory
    assert client2.get("/users", headers=_auth("root")).status_code == 200

    # seed(users=...) no longer exists: user seeding is a directory concern, off the Authorization object.
    orphan = Authorization(verification_keys=[SECRET], audience=OS_ID)
    with pytest.raises(TypeError, match="users"):
        orphan.seed(users=[("bob", {"role": "viewer"})])


def test_seed_admin_heals_a_lockout_but_respects_a_handover(tmp_path):
    """seed(admin=) re-grants the bootstrap admin ONLY when nobody holds an admin role any more.
    An operator who moved admin to someone else keeps that decision across restarts; an operator
    who demoted the last admin (lockout: the admin API can no longer repair itself) gets the
    bootstrap admin back on the next boot."""
    dbfile = str(tmp_path / "heal.db")

    def boot():
        a = Authorization(db=SqliteDb(db_file=dbfile))
        a.define_role("admin", ["agent_os:admin"])
        a.define_role("viewer", ["agents:*:read"])
        a.seed(admin="root")
        return a

    a1 = boot()
    assert a1.role_store.admin_subjects() == ["root"]

    # Handover: root demoted, carol promoted. A restart must not undo it.
    a1.role_store.assign("carol", "admin")
    a1.role_store.assign("root", "viewer")
    a2 = boot()
    assert a2.role_store.roles_of("root") == ["viewer"]
    assert a2.role_store.admin_subjects() == ["carol"]

    # Lockout: carol demoted too, nobody is admin. A restart heals it.
    a2.role_store.assign("carol", "viewer")
    assert a2.role_store.admin_subjects() == []
    a3 = boot()
    assert a3.role_store.roles_of("root") == ["admin"]
    assert a3.role_store.roles_of("carol") == ["viewer"]  # only the bootstrap subject is touched


def test_seed_admin_respects_a_handover_that_removed_the_bootstrap_role(tmp_path):
    """A handover that STRIPS the bootstrap subject's role entirely (leaving it with none) is
    respected across restarts, the same as a demotion. A missing role must not re-grant the
    bootstrap admin while another subject still holds admin: restoring on an empty role would put
    two admins back and silently undo the operator's revocation. Only a true lockout (nobody holds
    admin) heals, whether the bootstrap subject was demoted or fully stripped."""
    dbfile = str(tmp_path / "remove.db")

    def boot():
        a = Authorization(db=SqliteDb(db_file=dbfile))
        a.define_role("admin", ["agent_os:admin"])
        a.define_role("viewer", ["agents:*:read"])
        a.seed(admin="root")
        return a

    # Handover by removal: carol promoted, root's only role revoked outright (root now has none).
    a1 = boot()
    a1.role_store.assign("carol", "admin")
    a1.role_store.unassign("root", "admin")
    assert a1.role_store.roles_of("root") == [] and a1.role_store.admin_subjects() == ["carol"]

    a2 = boot()  # a restart must NOT restore root just because it has no role
    assert a2.role_store.roles_of("root") == []
    assert a2.role_store.admin_subjects() == ["carol"]

    # But a true lockout reached by removal (nobody holds admin) still heals on the next boot.
    a2.role_store.unassign("carol", "admin")
    assert a2.role_store.admin_subjects() == []
    a3 = boot()
    assert a3.role_store.roles_of("root") == ["admin"]


def test_seed_admin_falls_back_to_create_if_absent_when_holders_cannot_be_listed(tmp_path):
    """On a policy engine that cannot enumerate a role's holders, seed(admin=) cannot tell a handover
    from a fresh deploy, so it falls back to create-if-absent: grant the bootstrap subject a role
    only when it has none. A fresh deploy still bootstraps; a subject that already holds a role is
    left alone (rather than guessing at a handover it cannot see)."""
    from unittest.mock import patch

    from agno.os.authz.role_store import ManagedRoleStore

    authz = Authorization(db=SqliteDb(db_file=str(tmp_path / "fallback.db")))
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"])
    authz.role_store.assign("carol", "admin")  # another admin exists; the enumerable path would skip root

    # Holders cannot be listed -> fall back to create-if-absent. root has no role, so it is granted
    # (a fresh deploy must still bootstrap), even though carol is admin, because the fallback is blind.
    with patch.object(ManagedRoleStore, "admin_subjects", side_effect=NotImplementedError):
        authz.seed(admin="root")
    assert authz.role_store.roles_of("root") == ["admin"]

    # A subject that already holds a role is not overridden by the blind fallback.
    authz.role_store.assign("dave", "viewer")
    with patch.object(ManagedRoleStore, "admin_subjects", side_effect=NotImplementedError):
        authz.seed(admin="dave")
    assert authz.role_store.roles_of("dave") == ["viewer"]


def test_provider_override_takes_no_store(tmp_path):
    """authorization_provider= is the full override: combining it with a role store or engine
    would leave a store nothing enforces behind a mounted /authz, so it is refused."""
    from agno.os.authz.provider import AuthorizationContext, AuthorizationProvider
    from agno.os.authz.role_store import ManagedRoleStore

    class AllowAll(AuthorizationProvider):
        def check(self, ctx: AuthorizationContext) -> bool:
            return True

        def accessible_resource_ids(self, ctx: AuthorizationContext):
            return {"*"}

    db = SqliteDb(db_file=str(tmp_path / "xor.db"))
    with pytest.raises(ValueError, match="engine="):
        Authorization(db=db, authorization_provider=AllowAll(), role_store=ManagedRoleStore(db=db))


def test_served_verify_only_mounts_no_admin_api(tmp_path):
    """A served verify-only facade (no roles) mounts neither /authz nor /users -- the directory stays
    off, so an isolation / scope-based deployment gets a clean surface with no role machinery. Asked
    over HTTP with an admin-scoped token: 404 means not mounted (a mounted router answers 200/403)."""
    db = SqliteDb(db_file=str(tmp_path / "vo_served.db"))
    authz = Authorization(verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    client = TestClient(AgentOS(id=OS_ID, db=db, agents=_agents(), authorization=authz).get_app())
    admin = _auth("op", scopes=["agent_os:admin"])
    assert client.get("/agents", headers=admin).status_code == 200  # the OS itself serves
    assert client.get("/authz/roles", headers=admin).status_code == 404  # no roles -> no /authz
    assert client.get("/users", headers=admin).status_code == 404  # no directory -> no /users


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


def test_idp_roles_claim_one_liner(tmp_path):
    """roles_claim= is the external-IdP one-liner: the caller's role comes from a token claim, so you
    define what each role may do but never assign users. It also turns managed roles on by itself."""
    from unittest.mock import AsyncMock, patch

    authz = Authorization(
        db=SqliteDb(db_file=str(tmp_path / "idp.db")),
        verification_keys=[SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        roles_claim="role",
    )
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"])
    assert authz.role_store is not None  # roles_claim alone puts roles in play

    def htok(sub, role):
        payload = {"sub": sub, "aud": OS_ID, "role": role, "exp": int(time.time()) + 3600}
        return {"Authorization": f"Bearer {jwt.encode(payload, SECRET, algorithm='HS256')}"}

    client = TestClient(AgentOS(id=OS_ID, db=authz._db, agents=_agents(), authorization=authz).get_app())
    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        # role comes off the token claim, no assign() anywhere
        assert (
            client.post(
                "/agents/secret/runs", headers=htok("a", "admin"), data={"message": "hi", "stream": "false"}
            ).status_code
            == 200
        )
        assert client.get("/agents/research", headers=htok("b", "viewer")).status_code == 200
        assert (
            client.post(
                "/agents/research/runs", headers=htok("b", "viewer"), data={"message": "hi", "stream": "false"}
            ).status_code
            == 403
        )


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
    assert isinstance(authz.provider, DenyAll)


def test_issuer_on_the_object_is_enforced(tmp_path):
    """Authorization(issuer=) pins the ``iss`` claim on the served OS even though the released
    AuthorizationConfig has no such field: the object hands it to the middleware directly."""
    authz = Authorization(
        verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID, issuer="https://good/"
    )
    client = TestClient(
        AgentOS(
            id=OS_ID, db=SqliteDb(db_file=str(tmp_path / "iss.db")), agents=_agents(), authorization=authz
        ).get_app()
    )

    def tok(iss):
        payload = {"sub": "u", "aud": OS_ID, "iss": iss, "scopes": ["agents:read"], "exp": int(time.time()) + 3600}
        return {"Authorization": f"Bearer {jwt.encode(payload, SECRET, algorithm='HS256')}"}

    assert client.get("/agents", headers=tok("https://good/")).status_code == 200
    assert client.get("/agents", headers=tok("https://evil/")).status_code == 401


def test_audit_api_404s_when_audit_is_off(tmp_path):
    """The audit endpoints follow the same capability-absent -> 404 rule as the rest of the admin
    API. With audit off there is no readable sink, so /authz/audit and /authz/decisions return 404,
    not a misleading empty 200 a frontend cannot tell apart from an enabled-but-empty trail. With
    audit on, both serve 200."""

    def client(audit):
        db = SqliteDb(db_file=str(tmp_path / f"audit_{audit}.db"))
        authz = Authorization(
            db=db,
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            audit=audit,
        )
        authz.define_role("admin", ["agent_os:admin"])
        authz.seed(admin="root")
        return TestClient(AgentOS(id=OS_ID, db=db, agents=_agents(), authorization=authz).get_app())

    admin = _auth("root")

    off = client(False)
    assert off.get("/authz/roles", headers=admin).status_code == 200  # roles are still served
    assert off.get("/authz/audit", headers=admin).status_code == 404  # change trail off -> 404
    assert off.get("/authz/decisions", headers=admin).status_code == 404  # decision trail off -> 404

    on = client(True)
    assert on.get("/authz/audit", headers=admin).status_code == 200
    assert on.get("/authz/decisions", headers=admin).status_code == 200


def test_seeded_admin_not_in_directory_is_not_demoted_on_first_request(tmp_path):
    """A subject granted a role (seed(admin=) / role_store.assign) but never added to the directory
    keeps that role on their first request. Auto-provision creates the directory row but must NOT
    grant the default role over an existing one -- that would silently demote an admin. A truly
    role-less user still gets the default, so provisioning is not broken, only the demotion is."""
    from agno.os.authz.user_store import ManagedUserStore
    from agno.os.config import UserDirectoryConfig

    db = SqliteDb(db_file=str(tmp_path / "demote.db"))
    users = ManagedUserStore(db=db)  # alice deliberately NOT seeded into the directory
    authz = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    authz.define_role("viewer", ["agents:*:read"], default=True)
    authz.define_role("admin", ["agent_os:admin"])
    authz.seed(admin="alice")

    client = TestClient(
        AgentOS(
            id=OS_ID,
            db=db,
            agents=_agents(),
            user_directory=UserDirectoryConfig(user_store=users, auto_provision=True),
            authorization=authz,
        ).get_app()
    )
    client.get("/agents/research", headers=_auth("alice"))  # first request auto-provisions alice
    client.get("/agents/research", headers=_auth("dave"))  # unknown, role-less

    assert authz.role_store.roles_of("alice") == ["admin"]  # kept, NOT demoted to the default
    assert authz.role_store.roles_of("dave") == ["viewer"]  # role-less still gets the default
    assert users.get("alice") is not None and users.get("dave") is not None  # both provisioned
