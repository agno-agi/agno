"""Authorization over an async database.

The whole managed-roles stack -- the DB contract, the native engine, the stores, the audit
sink, the providers -- has both a sync and an async form, and the async form works against an
async SQLAlchemy backend (``AsyncSqliteDb``) as well as a sync one driven from the async path.
These tests cover three things:

1. The async storage/engine/store/audit round trips on an async DB.
2. Sync and async decision paths agree (both-variants parity).
3. The served AgentOS request path (route gate, per-resource gate, list filter) enforces
   managed roles when the OS db is async -- the end-to-end reason async is required.
"""

import asyncio
import time

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("aiosqlite")

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.db.sqlite.async_sqlite import AsyncSqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz.audit import DbAuditSink  # noqa: E402
from agno.os.authz.native_engine import NativePolicyEngine  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.authz.user_store import ManagedUserStore  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402

SECRET = "async-authz-secret-at-least-256-bits-xxxxxxxxxxxxxx"
OS_ID = "async-authz-os"


def test_native_engine_async_round_trip_on_async_db(tmp_path):
    """The engine's async methods author policy, assign, and decide on an async DB, with
    deny-overrides and the accessible/denied id sets all correct."""

    async def scenario():
        db = AsyncSqliteDb(db_file=str(tmp_path / "engine.db"))
        eng = NativePolicyEngine(db=db)
        await eng.aset_role_scopes("member", [("agents:*:read", "allow"), ("agents:secret:read", "deny")])
        await eng.aassign("bob", "member")
        assert await eng.aroles_of("bob") == ["member"]
        assert await eng.acheck_resource("agents", "x", "read", subject="bob") is True
        assert await eng.acheck_resource("agents", "secret", "read", subject="bob") is False  # deny wins
        assert await eng.acheck_resource("agents", "x", "run", subject="bob") is False  # no grant
        assert await eng.aaccessible_resource_ids("agents", "read", subject="bob") == {"*"}
        assert await eng.adenied_resource_ids("agents", "read", subject="bob") == {"secret"}
        await db.close()

    asyncio.run(scenario())


def test_sync_and_async_decisions_agree(tmp_path):
    """Both-variants parity: the same policy yields the same decision whether resolved through
    the sync path (sync DB) or the async path (async DB)."""
    sync_db = SqliteDb(db_file=str(tmp_path / "sync.db"))
    seng = NativePolicyEngine(db=sync_db)
    seng.set_role_scopes("member", [("agents:*:read", "allow"), ("agents:secret:read", "deny")])
    seng.assign("bob", "member")
    sync_decisions = {
        ("x", "read"): seng.check_resource("agents", "x", "read", subject="bob"),
        ("secret", "read"): seng.check_resource("agents", "secret", "read", subject="bob"),
        ("x", "run"): seng.check_resource("agents", "x", "run", subject="bob"),
    }

    async def async_side():
        adb = AsyncSqliteDb(db_file=str(tmp_path / "async.db"))
        aeng = NativePolicyEngine(db=adb)
        await aeng.aset_role_scopes("member", [("agents:*:read", "allow"), ("agents:secret:read", "deny")])
        await aeng.aassign("bob", "member")
        out = {
            ("x", "read"): await aeng.acheck_resource("agents", "x", "read", subject="bob"),
            ("secret", "read"): await aeng.acheck_resource("agents", "secret", "read", subject="bob"),
            ("x", "run"): await aeng.acheck_resource("agents", "x", "run", subject="bob"),
        }
        await adb.close()
        return out

    assert asyncio.run(async_side()) == sync_decisions
    assert sync_decisions == {("x", "read"): True, ("secret", "read"): False, ("x", "run"): False}


def test_managed_stores_and_audit_async_on_async_db(tmp_path):
    """ManagedRoleStore, ManagedUserStore and DbAuditSink round-trip on an async DB, and the
    change trail is written and read back."""

    async def scenario():
        db = AsyncSqliteDb(db_file=str(tmp_path / "stores.db"))
        audit = DbAuditSink(db=db)
        roles = ManagedRoleStore(db=db, audit=audit)
        users = ManagedUserStore(db=db, audit=audit)

        await roles.aset_role_scopes("member", ["agents:*:read"], name="Member", is_default=True, actor="admin")
        await roles.aassign("bob", "member", actor="admin")
        assert await roles.aroles_of("bob") == ["member"]
        assert await roles.adefault_role() == "member"
        assert await roles.acan_manage("bob") is False

        await users.aupsert("bob", email="bob@x.com", actor="admin")
        await users.aset_disabled("bob", True, actor="admin")
        assert await users.ais_disabled("bob") is True

        # first-login provisioning
        user, created = await users.aprovision_from_claims("newbie", {"email": "n@x.com"})
        assert created is True and user["id"] == "newbie"

        assert await roles.aaudit_count() > 0
        actions = [row["action"] for row in await audit.aread(limit=20)]
        assert "user.disabled" in actions
        await db.close()

    asyncio.run(scenario())


def _token(sub: str) -> str:
    return jwt.encode({"sub": sub, "aud": OS_ID, "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")


def _auth(sub: str) -> dict:
    return {"Authorization": f"Bearer {_token(sub)}"}


class _MockRunOutput:
    def to_dict(self):
        return {"run_id": "r1"}


def _served_os(tmp_path):
    """AgentOS whose OS db is async, with managed roles bound to it."""
    adb = AsyncSqliteDb(db_file=str(tmp_path / "served.db"))
    roles = ManagedRoleStore(db=adb)
    asyncio.run(roles.aset_role_scopes("runner", ["agents:research:run", "agents:research:read"]))
    asyncio.run(roles.aassign("alice", "runner"))
    asyncio.run(roles.aset_role_scopes("admin", ["agent_os:admin"]))
    asyncio.run(roles.aassign("carol", "admin"))
    os_ = AgentOS(
        id=OS_ID,
        agents=[Agent(id="research", name="R", db=InMemoryDb()), Agent(id="secret", name="S", db=InMemoryDb())],
        db=adb,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=roles.provider,
        ),
    )
    return os_


def test_served_agentos_enforces_managed_roles_on_async_db(tmp_path):
    """End-to-end: with the OS db async, the request-path gates (route + per-resource) enforce
    managed roles -- the reason the async variants are required, not just nice to have."""
    from unittest.mock import AsyncMock, patch

    client = TestClient(_served_os(tmp_path).get_app())

    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        # alice is granted research
        assert (
            client.post(
                "/agents/research/runs", headers=_auth("alice"), data={"message": "hi", "stream": "false"}
            ).status_code
            == 200
        )
        # alice is not granted secret
        assert (
            client.post(
                "/agents/secret/runs", headers=_auth("alice"), data={"message": "hi", "stream": "false"}
            ).status_code
            == 403
        )
        # carol is admin
        assert (
            client.post(
                "/agents/secret/runs", headers=_auth("carol"), data={"message": "hi", "stream": "false"}
            ).status_code
            == 200
        )
        # bob has no role
        assert (
            client.post(
                "/agents/research/runs", headers=_auth("bob"), data={"message": "hi", "stream": "false"}
            ).status_code
            == 403
        )


def test_served_agentos_list_filtering_on_async_db(tmp_path):
    """The list gate filters to the caller's accessible resources when the OS db is async."""
    client = TestClient(_served_os(tmp_path).get_app())
    r = client.get("/agents", headers=_auth("alice"))
    assert r.status_code == 200
    assert sorted(a["id"] for a in r.json()) == ["research"]  # secret is filtered out


def test_disabled_user_denied_over_async_directory(tmp_path):
    """The revocation kill-switch works when the directory is async: a disabled user is denied
    even with a valid token, enforced in the middleware over the async store."""
    from unittest.mock import AsyncMock, patch

    from agno.os.config import UserDirectoryConfig

    adb = AsyncSqliteDb(db_file=str(tmp_path / "dir.db"))
    store = ManagedUserStore(db=adb)
    asyncio.run(store.aupsert("dave", email="dave@x.com"))
    asyncio.run(store.aset_disabled("dave", True))

    os_ = AgentOS(
        id=OS_ID,
        agents=[Agent(id="research", name="R", db=InMemoryDb())],
        db=adb,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID
        ),
        user_directory=UserDirectoryConfig(user_store=store, auto_provision=True),
    )
    client = TestClient(os_.get_app())

    with patch.object(Agent, "arun", new_callable=AsyncMock) as m:
        m.return_value = _MockRunOutput()
        r = client.post("/agents/research/runs", headers=_auth("dave"), data={"message": "hi", "stream": "false"})
    assert r.status_code == 403  # disabled -> denied even with a valid token


def test_user_management_metrics_async_on_async_db(tmp_path):
    """The reads behind /users/metrics have async twins that work on an async DB, and the
    sync collector on a sync DB agrees with the async one."""
    from agno.os.authz.role_router import (
        acollect_user_management_metrics,
        collect_user_management_metrics,
    )

    adb = AsyncSqliteDb(db_file=str(tmp_path / "metrics.db"))
    roles = ManagedRoleStore(db=adb)
    users = ManagedUserStore(db=adb)

    async def seed():
        await roles.aset_role_scopes("admin", ["agent_os:admin"])
        await roles.aset_role_scopes("viewer", ["agents:*:read"])
        for user in ("alice", "bob", "carol", "dave"):
            await users.aupsert(user)
        await roles.aassign("alice", "admin")
        await roles.aassign("bob", "viewer")
        await roles.aassign("carol", "viewer")
        await users.aset_disabled("dave", True)

        assert await users.acount_by_status() == {"total": 4, "disabled": 1}
        assert await users.aids() == ["alice", "bob", "carol", "dave"]
        assert [row["count"] for row in await users.acreated_by_day()] == [4]
        assert await roles.aroles_of_many(["alice", "bob", "nobody"]) == {
            "alice": ["admin"],
            "bob": ["viewer"],
            "nobody": [],
        }
        metrics = await acollect_user_management_metrics(users, roles)
        assert (metrics.total, metrics.active, metrics.disabled, metrics.without_role) == (4, 3, 1, 1)
        assert [(r.role, r.count) for r in metrics.by_role] == [("admin", 1), ("viewer", 2)]

    asyncio.run(seed())

    # The served /users/metrics handler awaits these same twins, so it is async-clean;
    # it is not exercised end to end here because the users router's admin dependency
    # still calls role_store.can_manage synchronously, which the native engine refuses on
    # an async DB. That gap belongs to the admin routers as a whole, not to this endpoint.

    # parity: the sync collector on a sync DB produces the same numbers the async one does
    sdb = SqliteDb(db_file=str(tmp_path / "metrics_sync.db"))
    sroles, susers = ManagedRoleStore(db=sdb), ManagedUserStore(db=sdb)
    sroles.set_role_scopes("admin", ["agent_os:admin"])
    sroles.set_role_scopes("viewer", ["agents:*:read"])
    for user in ("alice", "bob", "carol", "dave"):
        susers.upsert(user)
    sroles.assign("alice", "admin")
    sroles.assign("bob", "viewer")
    sroles.assign("carol", "viewer")
    susers.set_disabled("dave", True)
    sync_metrics = collect_user_management_metrics(susers, sroles)
    async_metrics = asyncio.run(acollect_user_management_metrics(susers, sroles))
    assert sync_metrics.model_dump(exclude={"created_per_day"}) == async_metrics.model_dump(exclude={"created_per_day"})
    assert [r.count for r in sync_metrics.created_per_day] == [r.count for r in async_metrics.created_per_day] == [4]
