"""Manager alias behaviour on Postgres, the adapter production runs.

Runs against the live pgvector container (localhost:5532) with a unique
schema per run; skips cleanly when psycopg or the server is absent.
"""

import asyncio
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

from sqlalchemy import create_engine, text  # noqa: E402

from agno.db.base import SessionType  # noqa: E402
from agno.db.postgres import AsyncPostgresDb, PostgresDb  # noqa: E402
from agno.os.authz.native_engine import NativePolicyEngine  # noqa: E402
from agno.session.team import TeamSession  # noqa: E402

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def _server_reachable() -> bool:
    # A raw probe, not an adapter call: adapter methods catch and log
    # connection errors, so they cannot signal an absent server.
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def _postgres_server():
    if not _server_reachable():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")


@pytest.fixture
def schema(_postgres_server):
    name = f"manager_alias_{uuid.uuid4().hex[:8]}"
    yield name
    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))
    engine.dispose()


@pytest.fixture
def db(schema):
    database = PostgresDb(db_url=DB_URL, db_schema=schema)
    yield database
    database.db_engine.dispose()


def _seed_sessions(store):
    store.upsert_session(TeamSession(session_id="old", team_id="os-manager-internal", user_id="alice", created_at=1))
    store.upsert_session(TeamSession(session_id="new", team_id="super--agent", user_id="alice", created_at=1))
    store.upsert_session(TeamSession(session_id="user", team_id="super-agent", user_id="alice", created_at=1))


@pytest.mark.parametrize("spelling", ["super--agent", "os-manager-internal"])
def test_session_list_includes_rows_under_either_manager_spelling(db, spelling):
    _seed_sessions(db)
    rows = db.get_sessions(session_type=SessionType.TEAM, component_id=spelling)
    assert sorted(session.session_id for session in rows) == ["new", "old"]
    assert sorted(session.session_id for session in db.get_sessions(component_id=spelling)) == ["new", "old"]


def test_session_list_keeps_a_user_team_separate_from_the_manager(db):
    _seed_sessions(db)
    rows = db.get_sessions(session_type=SessionType.TEAM, component_id="super-agent")
    assert [session.session_id for session in rows] == ["user"]


@pytest.mark.parametrize("spelling", ["super--agent", "os-manager-internal"])
def test_async_session_list_includes_rows_under_either_manager_spelling(db, schema, spelling):
    _seed_sessions(db)

    async def scenario():
        store = AsyncPostgresDb(db_url=DB_URL, db_schema=schema)
        try:
            return await store.get_sessions(session_type=SessionType.TEAM, component_id=spelling)
        finally:
            await store.db_engine.dispose()

    assert sorted(session.session_id for session in asyncio.run(scenario())) == ["new", "old"]


def test_stored_deny_under_a_former_id_blocks_the_manager_until_flipped(db):
    role = "legacy"
    db.set_authz_role_policies(role, [("teams/*", "run", "allow"), ("teams/os-manager-internal", "run", "deny")])
    assert not NativePolicyEngine(db=db).check_scope("teams:super--agent:run", roles=[role])
    assert NativePolicyEngine(db=db).check_scope("teams:super-agent:run", roles=[role])

    db.upsert_authz_policy(role=role, resource="teams/super--agent", action="run", effect="allow")
    assert sorted(db.get_authz_role_policies(role)) == [
        ("teams/*", "run", "allow"),
        ("teams/super--agent", "run", "allow"),
    ]
    assert NativePolicyEngine(db=db).check_scope("teams:super--agent:run", roles=[role])


def test_policy_delete_removes_rows_under_either_manager_spelling(db):
    role = "legacy"
    db.set_authz_role_policies(role, [("teams/os-manager-internal", "run", "allow"), ("teams/docs", "run", "allow")])
    db.delete_authz_policy(role=role, resource="teams/super--agent", action="run")
    assert db.get_authz_role_policies(role) == [("teams/docs", "run", "allow")]
