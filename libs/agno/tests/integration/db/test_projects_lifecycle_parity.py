"""Work lifecycle parity on PostgreSQL and SQLite, sync and native async."""

import inspect
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.company import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def db(request, tmp_path):
    backend = request.param
    suffix = uuid4().hex[:12]
    kwargs = {
        "products_table": "products_" + suffix,
        "projects_table": "projects_" + suffix,
        "tasks_table": "tasks_" + suffix,
    }
    if "postgres" in backend:
        kwargs.update(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema="products_" + suffix)
        cls = AsyncPostgresDb if backend.startswith("async") else PostgresDb
    else:
        kwargs.update(db_file=str(tmp_path / "products.db"))
        cls = AsyncSqliteDb if backend.startswith("async") else SqliteDb
    database = cls(**kwargs)
    try:
        yield database
    finally:
        if "postgres" in backend:
            # Only this fixture's randomly named schema is removed.
            if isinstance(database, AsyncBaseDb):
                async with database.db_engine.begin() as conn:
                    await conn.execute(text('DROP SCHEMA IF EXISTS "' + database.db_schema + '" CASCADE'))
            else:
                with database.db_engine.begin() as conn:
                    conn.execute(text('DROP SCHEMA IF EXISTS "' + database.db_schema + '" CASCADE'))
        await call(database.close)


async def call(fn, /, *args, **kwargs):
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def manager(db):
    return AsyncCompanyManager(db) if isinstance(db, AsyncBaseDb) else CompanyManager(db)


@pytest.mark.asyncio
async def test_lifecycle_and_owner_guards(db):
    m = manager(db)
    assert await call(m.list_projects) == ([], 0)
    parent = await call(m.create, name="SDK", user_id="alice")
    record = await call(m.create_project, product_id=parent["id"], name="Ship", user_id="alice", scoped_user_id="alice")
    rid = record["id"]
    assert record["status"] == "proposed"
    assert await call(m.get_project, rid, user_id="bob") is None
    assert await call(m.update_project, rid, user_id="bob", outcome="No") is None
    assert await call(m.delete_project, rid, user_id="bob") is False
    assert await call(m.transition_project, project_id=rid, target="cancelled", reason="Stop", user_id="bob") is None
    changed = await call(m.update_project, rid, outcome="Changed")
    assert changed["outcome"] == "Changed"
    assert changed["updated_at"] >= record["created_at"]
    with pytest.raises(ValueError):
        await call(m.transition_project, project_id=rid, target="done", reason="Skip")
    with pytest.raises(ValueError):
        await call(m.transition_project, project_id=rid, target="cancelled", reason=" ")
    states = ["active", "done"]
    for state in states:
        kwargs = {"executor_type": "agent", "executor_id": "writer"} if state == "ready" else {}
        result = await call(
            m.transition_project, project_id=rid, target=state, reason="Reviewed", accepted_by="reviewer", **kwargs
        )
        assert result["status"] == state
    assert [entry["target"] for entry in result["transitions"]] == states
    assert all(entry["user_id"] == "reviewer" for entry in result["transitions"])
    with pytest.raises(ValueError):
        await call(m.transition_project, project_id=rid, target="cancelled", reason="Terminal")
    assert await call(m.restore_project, rid) is None
    assert await call(m.delete_project, rid)
    assert await call(m.get_project, rid) is None
    assert await call(m.update_project, rid, outcome="Deleted") is None
    assert await call(m.get_project, rid, include_deleted=True)
    assert (await call(m.list_projects))[1] == 0
    assert (await call(m.list_projects, include_deleted=True))[1] == 1
    assert await call(m.restore_project, rid, user_id="bob") is None
    assert (await call(m.restore_project, rid))["status"] == "done"
    assert await call(m.get_project, "missing") is None
    assert await call(m.transition_project, project_id="missing", target="cancelled", reason="Missing") is None


@pytest.mark.asyncio
async def test_filters_and_stable_paging(db):
    m = manager(db)
    parents = [await call(m.create, name="A"), await call(m.create, name="B")]
    now = int(time.time())
    for i, owner in enumerate(["alice", "bob", "alice", None, "alice", "bob"]):
        await call(
            db.create_project,
            {
                "id": str(i),
                "product_id": parents[i % 2]["id"],
                "name": "Same",
                "status": "proposed",
                "user_id": owner,
                "created_at": now,
                "transitions": [],
            },
        )
    await call(m.transition_project, project_id="0", target="cancelled", reason="Stop")
    pages = [await call(m.list_projects, user_id="alice", status="proposed", limit=1, page=p) for p in [1, 2]]
    assert [p[1] for p in pages] == [2, 2]
    assert [p[0][0]["id"] for p in pages] == ["4", "2"]
    assert (await call(m.list_projects, product_id=parents[1]["id"]))[1] == 3
    assert (await call(m.list_projects, status="cancelled"))[1] == 1
    assert (await call(m.list_projects, user_id="absent")) == ([], 0)


@pytest.mark.asyncio
async def test_validation_parent_visibility_and_immutable_fields(db):
    m = manager(db)
    parent = await call(m.create, name="SDK", user_id="alice")
    with pytest.raises(LookupError):
        await call(m.create_project, product_id=parent["id"], name="Hidden", user_id="bob", scoped_user_id="bob")
    record = await call(m.create_project, product_id=parent["id"], name="Work")
    for fields in [
        {"status": "done"},
        {"id": "other"},
        {"product_id": "other"},
        {"created_at": 0},
        {"deleted_at": 1},
        {"name": None},
        {"outcome": []},
    ]:
        with pytest.raises(ValueError):
            await call(m.update_project, record["id"], **fields)
        with pytest.raises(ValueError):
            await call(db.update_project, record["id"], **fields)
    for kwargs in [{"limit": 0}, {"page": 0}]:
        with pytest.raises(ValueError):
            await call(m.list_projects, **kwargs)
        with pytest.raises(ValueError):
            await call(db.get_projects, **kwargs)


@pytest.mark.asyncio
async def test_custom_table_migrations_and_configuration_roundtrip(db):
    m = manager(db)
    parent = await call(m.create, name="SDK")
    record = await call(m.create_project, product_id=parent["id"], name="Roundtrip", user_id="alice")
    assert await call(db.table_exists, db.projects_table_name)
    assert not await call(db.table_exists, "agno_company_projects")
    assert await call(db.get_latest_schema_version, db.projects_table_name)
    data = db.to_dict()
    assert data["projects_table"] == db.projects_table_name
    reopened = type(db).from_dict(data)
    try:
        assert reopened.projects_table_name == db.projects_table_name
        assert await call(reopened.get_project, record["id"], user_id="alice") == record
    finally:
        await call(reopened.close)
