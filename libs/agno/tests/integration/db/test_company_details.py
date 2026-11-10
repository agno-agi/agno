"""Company singleton persistence and optimistic edits across SQL adapters."""

import inspect
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb


async def call(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def db(request, tmp_path):
    if "postgres" in request.param:
        cls = AsyncPostgresDb if request.param.startswith("async") else PostgresDb
        db = cls(
            db_url=os.getenv("COMPANY_TEST_DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai"),
            db_schema="details_" + uuid4().hex,
        )
    else:
        cls = AsyncSqliteDb if request.param.startswith("async") else SqliteDb
        db = cls(db_file=str(tmp_path / "details.db"))
    yield db
    if "postgres" in request.param:
        statement = text('DROP SCHEMA IF EXISTS "' + db.db_schema + '" CASCADE')
        if isinstance(db, AsyncBaseDb):
            async with db.db_engine.begin() as conn:
                await conn.execute(statement)
        else:
            with db.db_engine.begin() as conn:
                conn.execute(statement)
    await call(db.close)


@pytest.mark.asyncio
async def test_singleton_preserves_edits_and_rejects_stale_writes(db):
    assert await call(db.get_company) is None
    initial = await call(db.initialize_company, "Original")
    assert set(initial) == {"id", "name", "description", "metadata", "created_at", "updated_at"}
    assert initial["description"] is None
    assert initial["metadata"] is None
    edited = await call(db.update_company, initial["updated_at"], name="Human edit", description="We make tools")
    assert edited["updated_at"] > initial["updated_at"]
    assert await call(db.update_company, initial["updated_at"], name="Stale") is None
    assert await call(db.initialize_company, "Deployment", "Stale config") == edited
    assert await call(db.get_company) == edited
    assert await call(db.update_company, edited["updated_at"]) == edited
    cleared = await call(db.update_company, edited["updated_at"], description=None)
    assert cleared["description"] is None
    assert cleared["name"] == "Human edit"
    with pytest.raises(ValueError):
        await call(db.update_company, cleared["updated_at"], id="second-company")
    with pytest.raises(ValueError):
        await call(db.update_company, cleared["updated_at"], name=" ")


@pytest.mark.asyncio
async def test_dynamic_context_is_fresh_and_authorized(db):
    from types import SimpleNamespace

    from agno.company.details import _company_instructions
    from agno.run.authorization import RunAuthorization, authorization_scope
    from agno.utils.agent import aexecute_instructions

    class Deny(RunAuthorization):
        def __init__(self):
            pass

        def require(self, *args):
            raise PermissionError("denied")

        async def arequire(self, *args):
            raise PermissionError("denied")

    initial = await call(db.initialize_company, "First", "First description")
    instructions = _company_instructions(db, ["Base"])
    assert "First description" in (await aexecute_instructions(instructions))[-1]
    await call(db.update_company, initial["updated_at"], description="Next run description")
    assert "Next run description" in (await aexecute_instructions(instructions))[-1]
    assert await aexecute_instructions(instructions, run_context=SimpleNamespace(authorization=Deny())) == ["Base"]
    # An active request wins over a stale authority left on a resumed run's context.
    with authorization_scope(lambda: None):
        resumed = await aexecute_instructions(instructions, run_context=SimpleNamespace(authorization=Deny()))
    assert "Next run description" in resumed[-1]


@pytest.mark.asyncio
async def test_concurrent_cold_start_survives_and_recovers(db):
    import asyncio
    from types import SimpleNamespace

    from agno.company.details import _seed_company

    # Independent adapter instances represent independent starting replicas.
    replicas = [type(db).from_dict(db.to_dict()) for _ in range(4)]
    config = SimpleNamespace(name="Initial", description=None)

    async def invoke(replica, method, *args, **kwargs):
        fn = getattr(replica, method)
        if isinstance(replica, AsyncBaseDb):
            return await fn(*args, **kwargs)
        return await asyncio.to_thread(fn, *args, **kwargs)

    try:
        # A replica that loses first-time table creation keeps starting, and its next attempt works.
        await asyncio.gather(
            *(_seed_company(SimpleNamespace(company=config, _company_db=replica)) for replica in replicas)
        )
        rows = [await invoke(replica, "initialize_company", "Initial") for replica in replicas]
        assert all(row == rows[0] for row in rows)
        edits = await asyncio.gather(
            *(
                invoke(replica, "update_company", rows[0]["updated_at"], name="Winner " + str(index))
                for index, replica in enumerate(replicas)
            )
        )
        assert sum(row is not None for row in edits) == 1
        winner = next(row for row in edits if row is not None)
        assert await call(db.get_company) == winner
    finally:
        for replica in replicas:
            await call(replica.close)


async def _company_rows(db):
    statement = text(
        f"SELECT COUNT(*) FROM {db.db_schema + '.' if hasattr(db, 'db_schema') else ''}{db.company_table_name}"
    )
    if isinstance(db, AsyncBaseDb):
        async with db.db_engine.connect() as conn:
            return (await conn.execute(statement)).scalar()
    with db.db_engine.connect() as conn:
        return conn.execute(statement).scalar()


@pytest.mark.asyncio
async def test_configuration_updates_the_one_row_until_someone_edits_it(db):
    seeded = await call(db.initialize_company, "Company")
    changed = await call(db.initialize_company, "Acme", "What Acme does")
    assert (changed["name"], changed["description"]) == ("Acme", "What Acme does")
    assert changed["created_at"] == changed["updated_at"] > seeded["updated_at"]
    assert await _company_rows(db) == 1
    # A client holding the earlier version must reload rather than overwrite.
    assert await call(db.update_company, seeded["updated_at"], name="Stale") is None

    edited = await call(db.update_company, changed["updated_at"], name="Human edit")
    assert edited["updated_at"] > edited["created_at"]
    assert await call(db.initialize_company, "Deployment", "Later config") == edited
    assert await _company_rows(db) == 1


@pytest.mark.asyncio
async def test_unchanged_configuration_does_not_move_the_version(db):
    seeded = await call(db.initialize_company, "Acme", "What Acme does")
    assert await call(db.initialize_company, "Acme", "What Acme does") == seeded


async def _set_metadata(db, value: str) -> None:
    table = (
        f'"{db.db_schema}"."{db.company_table_name}"'
        if "postgres" in type(db).__name__.lower()
        else db.company_table_name
    )
    statement = text(f"UPDATE {table} SET metadata = '{value}' WHERE id = 'company'")
    if isinstance(db, AsyncBaseDb):
        async with db.db_engine.begin() as conn:
            await conn.execute(statement)
    else:
        with db.db_engine.begin() as conn:
            conn.execute(statement)


@pytest.mark.asyncio
async def test_metadata_is_not_human_editable_and_survives_reseed_and_edits(db):
    initial = await call(db.initialize_company, "Original")
    with pytest.raises(ValueError):
        await call(db.update_company, initial["updated_at"], metadata={"plan": "pro"})
    await _set_metadata(db, '{"plan": "pro"}')
    reseeded = await call(db.initialize_company, "Renamed in config")
    assert reseeded["name"] == "Renamed in config"
    assert reseeded["metadata"] == {"plan": "pro"}
    edited = await call(db.update_company, reseeded["updated_at"], description="Human edit")
    assert edited["metadata"] == {"plan": "pro"}


@pytest.mark.asyncio
async def test_company_tool_patch_and_restart_across_adapters(db):
    import json

    from agno.company.details import _company_instructions
    from agno.run import RunContext
    from agno.tools.company import CompanyTools

    await call(db.initialize_company, "Initial", "Initial description")
    toolkit = CompanyTools(db)
    context = RunContext(run_id="edit", session_id="chat", user_id="alice")
    functions = [toolkit.aupdate_company_details]
    if not isinstance(db, AsyncBaseDb):
        functions.append(toolkit.update_company_details)
    for edit in functions:
        result = json.loads(await call(edit, {"name": "Acme", "description": "Warehouse robots"}, context))
        assert (result["name"], result["description"]) == ("Acme", "Warehouse robots")
        result = json.loads(await call(edit, {"name": "Acme Inc"}, context))
        assert (result["name"], result["description"]) == ("Acme Inc", "Warehouse robots")
        result = json.loads(await call(edit, {"description": None}, context))
        assert (result["name"], result["description"]) == ("Acme Inc", None)
    saved = await call(db.get_company)
    await call(db.close)
    fresh = type(db).from_dict(db.to_dict())
    try:
        assert await call(fresh.initialize_company, "Deployment", "Different configuration") == saved
        instructions = _company_instructions(fresh, [])
        assert "Acme Inc" in (await instructions.__acall__())[-1]
    finally:
        await call(fresh.close)


@pytest.mark.asyncio
async def test_company_tool_conflict_across_adapters(db, monkeypatch):
    from agno.tools.company import CompanyTools

    await call(db.initialize_company, "Initial")
    toolkit = CompanyTools(db)
    update = db.update_company
    calls = []

    def competing_update(expected_updated_at, **fields):
        calls.append(expected_updated_at)
        assert update(expected_updated_at, name="Winner") is not None
        return update(expected_updated_at, **fields)

    async def acompeting_update(expected_updated_at, **fields):
        calls.append(expected_updated_at)
        assert await update(expected_updated_at, name="Winner") is not None
        return await update(expected_updated_at, **fields)

    monkeypatch.setattr(db, "update_company", acompeting_update if isinstance(db, AsyncBaseDb) else competing_update)
    functions = [toolkit.aupdate_company_details]
    if not isinstance(db, AsyncBaseDb):
        functions.append(toolkit.update_company_details)
    for edit in functions:
        calls.clear()
        with pytest.raises(ValueError, match="changed concurrently.*Stop without retrying"):
            await call(edit, {"name": "Loser"})
        assert len(calls) == 1
        assert (await call(db.get_company))["name"] == "Winner"
