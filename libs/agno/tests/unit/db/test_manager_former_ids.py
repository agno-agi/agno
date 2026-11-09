"""Startup refuses managed-role policies that name a manager ID from before Agno 3.2.

Postgres cases run against the live pgvector container (localhost:5532) with a
unique schema per run, and skip cleanly when psycopg or the server is absent.
"""

import inspect
import os
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, Authorization

DB_URL = os.getenv("COMPANY_TEST_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")
SECRET = "former-manager-id-test-key-at-least-32-characters"


def _authorization():
    return Authorization(verification_keys=[SECRET], algorithm="HS256", audience="former").define_role(
        "member", ["teams:*:run"]
    )


def _wired(db):
    # define_role writes at setup and needs a synchronous database, so declare roles without writing.
    auth = Authorization(verification_keys=[SECRET], algorithm="HS256", audience="former")
    auth._declare_roles()
    return auth._wire(db)


async def call(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _postgres_available() -> bool:
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def db(request, tmp_path):
    if "postgres" not in request.param:
        store = (AsyncSqliteDb if request.param.startswith("async") else SqliteDb)(db_file=str(tmp_path / "former.db"))
        yield store
        await call(store.close)
        return
    pytest.importorskip("psycopg")
    if not _postgres_available():
        pytest.skip(f"Postgres server not reachable at {DB_URL}")
    from agno.db.postgres import AsyncPostgresDb, PostgresDb

    schema = f"former_ids_{uuid.uuid4().hex[:8]}"
    store = (AsyncPostgresDb if request.param.startswith("async") else PostgresDb)(db_url=DB_URL, db_schema=schema)
    yield store
    await call(store.close)
    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", ["deny", "allow"])
@pytest.mark.parametrize(
    "resource",
    [
        "teams/os-manager-internal",
        "agents/company-manager-internal",
        "agents/platform-builder-internal",
        "agents/platform-manager-internal",
    ],
)
async def test_former_id_policy_blocks_startup_on_every_adapter(db, resource, effect):
    auth = _wired(db)
    await call(db.set_authz_role_policies, "legacy", [("teams/*", "run", "allow"), (resource, "run", effect)])
    with pytest.raises(ValueError, match="renamed in Agno 3.2") as raised:
        await auth._araise_if_former_manager_policies()
    assert f"legacy: {resource} run ({effect})" in str(raised.value)
    assert "os-manager-internal -> super--agent" in str(raised.value)


@pytest.mark.asyncio
async def test_current_and_user_ids_do_not_block_startup(db):
    auth = _wired(db)
    await call(
        db.set_authz_role_policies,
        "current",
        [("teams/super--agent", "run", "deny"), ("teams/super-agent", "run", "allow"), ("teams/*", "run", "allow")],
    )
    await auth._araise_if_former_manager_policies()


def test_application_refuses_to_start_and_starts_once_policies_are_updated(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "app.db"))
    db.set_authz_role_policies("legacy", [("teams/*", "run", "allow"), ("teams/os-manager-internal", "run", "deny")])
    app = AgentOS(id="former", db=db, authorization=_authorization(), telemetry=False).get_app()
    with pytest.raises(ValueError, match="renamed in Agno 3.2"):
        with TestClient(app):
            pass

    db.set_authz_role_policies("legacy", [("teams/*", "run", "allow"), ("teams/super--agent", "run", "deny")])
    app = AgentOS(id="former", db=db, authorization=_authorization(), telemetry=False).get_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    db.close()


def test_role_declared_in_code_with_a_former_id_blocks_startup(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "code.db"))
    auth = _authorization().define_role("legacy", ["teams:os-manager-internal:run"])
    app = AgentOS(id="former", db=db, authorization=auth, telemetry=False).get_app()
    with pytest.raises(ValueError, match="renamed in Agno 3.2"):
        with TestClient(app):
            pass
    db.close()
