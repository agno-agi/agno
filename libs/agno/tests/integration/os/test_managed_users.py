"""The credential-less user directory (no-IdP tier).

Covers the store itself (in-memory + SQLite), the admin HTTP surface
(``/authz/users`` with roles merged in), and the enforcement value-add: a
disabled user is denied at the gate even with a valid token, and just-in-time
provisioning creates a directory row from token claims.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.os.authz.audit import AuditEvent, AuditSink, DbAuditSink  # noqa: E402
from agno.os.authz.user_store import ManagedUserStore  # noqa: E402

SECRET = "managed-users-secret-at-least-256-bits-long-padding-xxxxxx"
OS_ID = "managed-users-os"


class _CapturingSink(AuditSink):
    def __init__(self):
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def _token(sub: str, **claims) -> str:
    payload = {
        "sub": sub,
        "aud": OS_ID,
        "scopes": claims.pop("scopes", []),
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    payload.update(claims)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _auth(sub: str, **claims) -> dict:
    return {"Authorization": f"Bearer {_token(sub, **claims)}"}


# ----------------------------------------------------------------- store unit
@pytest.mark.parametrize("db_url", [None, "sqlite"])
def test_store_crud_and_disable(tmp_path, db_url):
    url = None if db_url is None else f"sqlite:///{tmp_path / 'users.db'}"
    store = ManagedUserStore(db_url=url)

    # create
    u = store.upsert("u1", email="u1@co", name="One")
    assert u["id"] == "u1" and u["email"] == "u1@co" and u["disabled"] is False
    assert store.get("u1")["name"] == "One"

    # partial update keeps untouched fields
    store.upsert("u1", name="Uno")
    after = store.get("u1")
    assert after["name"] == "Uno" and after["email"] == "u1@co"

    # list newest-first
    store.upsert("u2", email="u2@co")
    ids = [u["id"] for u in store.list()]
    assert set(ids) == {"u1", "u2"}

    # disable / enable + is_disabled fast path
    assert store.is_disabled("u1") is False
    store.set_disabled("u1", True)
    assert store.is_disabled("u1") is True
    assert [u["id"] for u in store.list(include_disabled=False)] == ["u2"]
    store.set_disabled("u1", False)
    assert store.is_disabled("u1") is False

    # unknown subject is not disabled (app may mint tokens for unseen users)
    assert store.is_disabled("ghost") is False

    # remove
    assert store.remove("u2") is True
    assert store.get("u2") is None
    assert store.remove("u2") is False


def test_store_emits_audit_with_actor_and_diff():
    sink = _CapturingSink()
    store = ManagedUserStore(audit=sink)

    store.upsert("u1", email="u1@co", actor="admin")
    store.upsert("u1", name="One", actor="admin")  # update
    store.set_disabled("u1", True, actor="admin")
    store.set_disabled("u1", True, actor="admin")  # no-op, no event
    store.set_disabled("u1", False, actor="admin")
    store.remove("u1", actor="admin")

    actions = [(e.action, e.target, e.actor) for e in sink.events]
    assert actions == [
        ("user.created", "u1", "admin"),
        ("user.updated", "u1", "admin"),
        ("user.disabled", "u1", "admin"),
        ("user.enabled", "u1", "admin"),
        ("user.removed", "u1", "admin"),
    ]


def test_provision_from_claims_is_idempotent():
    store = ManagedUserStore()
    created = store.provision_from_claims("u1", {"email": "u1@co", "name": "One"})
    assert created["email"] == "u1@co" and created["name"] == "One"
    # second call is a no-op, returns existing (doesn't overwrite)
    again = store.provision_from_claims("u1", {"email": "changed@co"})
    assert again["email"] == "u1@co"


# ----------------------------------------------------- HTTP API + enforcement
pytest.importorskip("sqlalchemy")  # managed roles persist/enforce via the native engine + SQLAlchemy

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz.role_router import get_roles_router  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402


def _db_url() -> str:
    """A throwaway file-backed SQLite URL. Managed roles require a DB (no in-memory
    mode); file-backed so the same DB is visible across the threads TestClient uses."""
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".authz.db")
    os.close(fd)
    return f"sqlite:///{path}"


def _os(role_store, user_store, **cfg):
    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    return AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=role_store.provider,
            user_store=user_store,
            **cfg,
        ),
    )


def test_users_api_crud_and_role_merge():
    roles = ManagedRoleStore(db_url=_db_url())
    roles.set_role_scopes("admin", ["agent_os:admin"])
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("alice", "admin")
    users = ManagedUserStore(db_url=_db_url())  # AgentOS requires a persistable directory

    app = _os(roles, users).get_app()
    app.include_router(get_roles_router(roles, user_store=users))
    client = TestClient(app)

    # create a user
    r = client.post("/authz/users", headers=_auth("alice"), json={"id": "bob", "email": "bob@co"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "bob" and r.json()["role"] is None and r.json()["status"] == "active"

    # give bob a role; the user view merges it in (singular: one role per user)
    roles.assign("bob", "viewer")
    got = client.get("/authz/users/bob", headers=_auth("alice")).json()
    assert got["email"] == "bob@co" and got["role"] == "viewer"

    # list is paginated ({data, meta}) and includes bob with his role
    listed = client.get("/authz/users", headers=_auth("alice")).json()["data"]
    assert any(u["id"] == "bob" and u["role"] == "viewer" for u in listed)

    # fuzzy search filters by id/email/name, case-insensitive, before pagination
    found = client.get("/authz/users?search=BOB", headers=_auth("alice")).json()
    assert [u["id"] for u in found["data"]] == ["bob"] and found["meta"]["total_count"] == 1
    assert [u["id"] for u in client.get("/authz/users?search=bob@co", headers=_auth("alice")).json()["data"]] == ["bob"]
    nothing = client.get("/authz/users?search=zzz-no-match", headers=_auth("alice")).json()
    assert nothing["data"] == [] and nothing["meta"]["total_count"] == 0

    # sorting: any USER_SORT_FIELDS member, asc/desc; unknown field is a 422
    client.post("/authz/users", headers=_auth("alice"), json={"id": "ann", "email": "ann@co"})
    by_id = client.get("/authz/users?sort_by=id&sort_order=asc", headers=_auth("alice")).json()["data"]
    assert [u["id"] for u in by_id] == sorted(u["id"] for u in by_id)
    assert client.get("/authz/users?sort_by=evil", headers=_auth("alice")).status_code == 422

    # update + delete; PATCH {"disabled": ...} is the revocation kill-switch
    client.patch("/authz/users/bob", headers=_auth("alice"), json={"name": "Bob"})
    assert client.get("/authz/users/bob", headers=_auth("alice")).json()["name"] == "Bob"
    disabled = client.patch("/authz/users/bob", headers=_auth("alice"), json={"disabled": True}).json()
    assert disabled["status"] == "disabled" and disabled["disabled"] is True
    assert users.is_disabled("bob") is True
    enabled = client.patch("/authz/users/bob", headers=_auth("alice"), json={"disabled": False}).json()
    assert enabled["status"] == "active" and users.is_disabled("bob") is False
    assert client.delete("/authz/users/bob", headers=_auth("alice")).json()["deleted"] is True
    assert client.get("/authz/users/bob", headers=_auth("alice")).status_code == 404


def test_users_api_is_admin_only():
    roles = ManagedRoleStore(db_url=_db_url())
    roles.set_role_scopes("admin", ["agent_os:admin"])
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("alice", "admin")
    roles.assign("bob", "viewer")
    users = ManagedUserStore(db_url=_db_url())  # AgentOS requires a persistable directory

    app = _os(roles, users).get_app()
    app.include_router(get_roles_router(roles, user_store=users))
    client = TestClient(app)

    assert client.get("/authz/users", headers=_auth("bob")).status_code == 403  # non-admin
    assert client.get("/authz/users").status_code == 401  # anonymous


def test_disabled_user_is_denied_even_with_valid_token():
    roles = ManagedRoleStore(db_url=_db_url())
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("bob", "viewer")
    users = ManagedUserStore(db_url=_db_url())  # AgentOS requires a persistable directory
    users.upsert("bob", email="bob@co")

    client = TestClient(_os(roles, users).get_app())

    # bob (viewer) can read while active
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 200

    # disable bob -> denied on the next request despite the still-valid token + role
    users.set_disabled("bob", True)
    blocked = client.get("/agents/research-agent", headers=_auth("bob"))
    assert blocked.status_code == 403
    assert "disabled" in blocked.json()["detail"].lower()

    # re-enable -> allowed again
    users.set_disabled("bob", False)
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 200


def test_disabled_user_is_denied_on_websocket():
    """The kill-switch must also fire on the WebSocket connect path, not just HTTP:
    a disabled user with a valid token is rejected at WS authenticate."""
    import json as _json

    roles = ManagedRoleStore(db_url=_db_url())
    roles.set_role_scopes("viewer", ["agents:*:read", "workflows:*:run"])
    roles.assign("bob", "viewer")
    users = ManagedUserStore(db_url=_db_url())  # AgentOS requires a persistable directory
    users.upsert("bob", email="bob@co")

    client = TestClient(_os(roles, users).get_app())

    def _auth_result():
        with client.websocket_connect("/workflows/ws") as ws:
            for _ in range(8):
                if _json.loads(ws.receive_text()).get("event") == "connected":
                    break
            ws.send_text(_json.dumps({"action": "authenticate", "token": _token("bob", scopes=["workflows:run"])}))
            for _ in range(8):
                frame = _json.loads(ws.receive_text())
                if frame.get("event") in ("authenticated", "auth_error"):
                    return frame
        raise AssertionError("no auth result frame within 8 messages")

    # active -> authenticates over WS
    assert _auth_result()["event"] == "authenticated"

    # disabled -> rejected at WS authenticate despite a valid token
    users.set_disabled("bob", True)
    err = _auth_result()
    assert err["event"] == "auth_error" and err.get("error_type") == "user_disabled", err


def test_auto_provision_from_claims_at_the_gate():
    roles = ManagedRoleStore(db_url=_db_url())
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("carol", "viewer")
    users = ManagedUserStore(db_url=_db_url())  # AgentOS requires a persistable directory

    client = TestClient(_os(roles, users, auto_provision_users=True).get_app())

    assert users.get("carol") is None
    # carol's first request provisions her from the token claims
    r = client.get("/agents/research-agent", headers=_auth("carol", email="carol@co", name="Carol"))
    assert r.status_code == 200
    provisioned = users.get("carol")
    assert provisioned is not None and provisioned["email"] == "carol@co" and provisioned["name"] == "Carol"


def test_stores_share_one_agno_db(tmp_path):
    """Passing the same agno db to the role/user/audit stores reuses its engine,
    so everything lives in one database (no second db_url to keep in sync)."""
    import sqlalchemy as sa

    from agno.db.sqlite import SqliteDb

    shared = SqliteDb(db_file=str(tmp_path / "shared.db"))
    r = ManagedRoleStore(db=shared)
    u = ManagedUserStore(db=shared)
    a = DbAuditSink(db=shared)  # noqa: F841 (constructed for table creation)

    r.set_role_scopes("viewer", ["agents:*:read"])
    r.assign("bob", "viewer")
    u.upsert("bob", email="bob@co")
    a.record(AuditEvent(action="role.set_scopes", actor="admin", target="viewer", timestamp=1))

    # all authz tables live in the single shared engine (native policy + grouping,
    # users, and the audit trail). Tables are created on first use by the db layer,
    # which is why each store is exercised above before this assertion.
    tables = set(sa.inspect(shared.db_engine).get_table_names())
    assert {
        "agno_authz_policy",
        "agno_authz_grouping",
        "agno_authz_users",
        "agno_authz_audit",
    } <= tables
    assert r.roles_of("bob") == ["viewer"]
    assert u.get("bob")["email"] == "bob@co"


def test_a_db_that_cannot_store_authz_is_refused():
    """A backend that does not implement the authorization contract must be rejected,
    rather than duck-typed for a SQLAlchemy engine and failing somewhere later."""
    from agno.db.in_memory import InMemoryDb
    from agno.os.authz._db import require_authz_db, supports_authz

    assert supports_authz(InMemoryDb()) is False
    assert supports_authz(None) is False
    with pytest.raises(RuntimeError, match="does not support authorization storage"):
        require_authz_db(InMemoryDb())


def test_agentos_adopts_its_db_so_the_kill_switch_persists(tmp_path):
    """Regression: a user directory created without a db must not stay in-memory.

    ManagedUserStore silently fell back to a process-local dict, so disabling a user
    -- the revocation that is supposed to outlive a valid token -- vanished on restart
    and was never seen by another replica. Its sibling ManagedRoleStore refuses to run
    unpersisted at all; this makes the directory consistent by having AgentOS lend it
    the OS database, carrying any rows written beforehand across.
    """
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.os import AgentOS
    from agno.os.authz.role_store import ManagedRoleStore
    from agno.os.config import AuthorizationConfig

    db_file = str(tmp_path / "os.db")
    os_db = SqliteDb(db_file=db_file)

    users = ManagedUserStore()  # no db: the shape that used to be silently in-memory
    users.upsert("bob")
    users.set_disabled("bob", True)
    assert users.is_bound is False

    roles = ManagedRoleStore(db_url=f"sqlite:///{db_file}")
    roles.set_role_scopes("admin", ["agent_os:admin"])
    AgentOS(
        id="user-adopt-os",
        agents=[Agent(id="a1", name="A", db=os_db)],
        db=os_db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=["k" * 40], algorithm="HS256", role_store=roles, user_store=users
        ),
    ).get_app()

    # adopted, and the revocation made before adoption came across
    assert users.is_bound is True
    assert users.is_disabled("bob") is True

    # a second worker on the same database agrees
    replica = ManagedUserStore(db=SqliteDb(db_file=db_file))
    assert replica.is_disabled("bob") is True
    assert [u["id"] for u in replica.list()] == ["bob"]


def test_in_memory_directory_still_works_standalone():
    """The in-memory mode stays supported for tests/dev when there is no AgentOS db."""
    users = ManagedUserStore()
    users.upsert("ana", email="ana@example.com")
    users.set_disabled("ana", True)
    assert users.is_bound is False
    assert users.is_disabled("ana") is True


def test_user_store_without_a_persistable_db_fails_fast():
    """A user directory that cannot persist is not a deployment mode.

    It backs the disabled-user kill switch, so an in-memory one means a revocation is
    lost on restart and never reaches another replica -- the control silently does
    nothing. ManagedRoleStore already refuses this; the two must agree, otherwise the
    weaker of the pair decides how safe the deployment is.
    """
    from agno.agent import Agent
    from agno.db.in_memory import InMemoryDb
    from agno.os import AgentOS
    from agno.os.authz.role_store import ManagedRoleStore
    from agno.os.config import AuthorizationConfig

    non_sql_db = InMemoryDb()  # stands in for any db with no SQLAlchemy engine (e.g. Mongo)
    roles = ManagedRoleStore(db_url="sqlite:///:memory:")
    roles.set_role_scopes("admin", ["agent_os:admin"])

    with pytest.raises(ValueError, match="needs a SQL database"):
        AgentOS(
            id="unpersisted-users-os",
            agents=[Agent(id="a1", name="A", db=non_sql_db)],
            db=non_sql_db,
            authorization=True,
            authorization_config=AuthorizationConfig(
                verification_keys=["k" * 40],
                algorithm="HS256",
                role_store=roles,
                user_store=ManagedUserStore(),  # bare: nothing to persist into
            ),
        ).get_app()


def test_deleting_a_user_revokes_their_roles_no_access_reversal():
    """Revocation-reversal regression (ADM-1). Deleting a user must NOT restore access:
    the directory row is the kill-switch tombstone (absence reads as 'not disabled'), so
    deleting a disabled user while their role assignment survives would re-grant their
    still-valid token. Delete now cascades the role revocation, leaving them access-less."""
    roles = ManagedRoleStore(db_url=_db_url())
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.set_role_scopes("admin", ["agent_os:admin"])
    roles.assign("alice", "admin")
    users = ManagedUserStore(db_url=_db_url())

    app = _os(roles, users).get_app()
    app.include_router(get_roles_router(roles, user_store=users))
    client = TestClient(app)

    client.post("/authz/users", headers=_auth("alice"), json={"id": "bob", "email": "bob@co"})
    roles.assign("bob", "viewer")
    # bob can read while enabled and assigned
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 200
    # revoke via disable
    client.patch("/authz/users/bob", headers=_auth("alice"), json={"disabled": True})
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 403
    # delete the disabled user -> role revoked in the same op, tombstone gone
    assert client.delete("/authz/users/bob", headers=_auth("alice")).status_code == 200
    assert roles.roles_of("bob") == [], "delete must revoke the user's role assignments"
    # bob's still-valid token must NOT regain access (would be 200 before the fix)
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 403


def test_profile_upsert_does_not_clobber_the_disabled_flag():
    """Lost-update regression (ADM-3). A profile edit (or JIT provision) must never write
    `disabled`: it is set only by the explicit, atomic set_disabled. Otherwise a profile
    edit carrying a stale snapshot would silently un-revoke a disabled user."""
    users = ManagedUserStore(db_url=_db_url())
    users.upsert("bob", email="bob@co")
    users.set_disabled("bob", True)
    assert users.is_disabled("bob") is True

    # a profile edit (email/name) must leave `disabled` untouched
    users.upsert("bob", name="Bob R.")
    assert users.is_disabled("bob") is True, "upsert reverted the revocation"
    assert users.get("bob")["name"] == "Bob R."

    # re-enable is still explicit and works
    users.set_disabled("bob", False)
    assert users.is_disabled("bob") is False
