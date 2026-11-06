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
    assert set(initial) == {"id", "name", "description", "created_at", "updated_at"}
    assert initial["description"] is None
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

    class Deny:
        def require(self, *args):
            raise PermissionError("denied")

        async def arequire(self, *args):
            raise PermissionError("denied")

    initial = await call(db.initialize_company, "First", "First description")
    instructions = _company_instructions(db, ["Base"])
    assert "First description" in (await call(instructions))[-1]
    await call(db.update_company, initial["updated_at"], description="Next run description")
    assert "Next run description" in (await call(instructions))[-1]
    assert await call(instructions, SimpleNamespace(authorization=Deny())) == ["Base"]
