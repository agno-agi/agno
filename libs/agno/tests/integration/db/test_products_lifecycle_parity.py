"""Product lifecycle parity on PostgreSQL and SQLite, sync and native async."""

import inspect
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.agent import Agent
from agno.company import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.db.utils import db_from_dict

EMPTY_COUNTS = {
    "projects": 0,
    "tasks": dict.fromkeys(["backlog", "ready", "in_progress", "in_review", "done", "cancelled"], 0),
}


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def db(request, tmp_path):
    backend = request.param
    suffix = uuid4().hex[:12]
    kwargs = {"products_table": "products_" + suffix}
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
    assert await call(m.list) == ([], 0)
    a = await call(m.create, name="SDK", purpose="Build", metadata={"nested": [1, {"yes": True}]}, user_id="alice")
    b = await call(m.create, name="SDK", user_id="bob")
    assert set(a) == {"id", "name", "purpose", "metadata", "user_id", "created_at", "updated_at", "deleted_at"}
    assert a["user_id"] == "alice" and a["updated_at"] is None
    assert await call(m.get, a["id"], user_id="alice") == {**a, "counts": EMPTY_COUNTS}
    assert await call(m.get, a["id"], user_id="bob") is None
    assert await call(m.update, a["id"], user_id="bob", name="stolen") is None
    assert await call(m.delete, a["id"], user_id="bob") is False
    assert await call(m.get, a["id"]) == {**a, "counts": EMPTY_COUNTS}
    changed = await call(m.update, a["id"], user_id="alice", purpose=None, metadata=None, name="Framework")
    # Clearing metadata resets the archive policy to its default.
    assert changed["purpose"] is None and changed["metadata"] == {"archive_window_days": 14}
    assert changed["created_at"] == a["created_at"] and changed["updated_at"] >= a["created_at"]
    assert await call(m.restore, a["id"]) is None
    assert await call(m.delete, a["id"], user_id="alice") is True
    assert await call(m.delete, a["id"], user_id="alice") is False
    assert await call(m.get, a["id"]) is None
    assert await call(m.update, a["id"], purpose="deleted") is None
    archived = await call(m.get, a["id"], include_deleted=True)
    assert archived["deleted_at"] is not None
    assert await call(m.get, a["id"], user_id="bob", include_deleted=True) is None
    assert (await call(m.list))[1] == 1
    assert (await call(m.list, include_deleted=True))[1] == 2
    assert await call(m.restore, a["id"], user_id="bob") is None
    restored = await call(m.restore, a["id"], user_id="alice")
    assert restored["deleted_at"] is None and restored["name"] == "Framework"
    # None is deliberately unscoped on every operation.
    assert (await call(m.update, b["id"], purpose="Unscoped"))["purpose"] == "Unscoped"
    assert await call(m.delete, b["id"])
    assert (await call(m.restore, b["id"]))["user_id"] == "bob"
    assert await call(m.get, "missing") is None
    assert await call(m.update, "missing", name="No") is None
    assert await call(m.delete, "missing") is False
    assert await call(m.restore, "missing") is None


@pytest.mark.asyncio
async def test_filters_and_stable_paging(db):
    now = int(time.time())
    for i, owner in enumerate(["alice", "bob", "alice", None, "alice", "bob"]):
        await call(
            db.create_product,
            {
                "id": str(i),
                "name": "Same name",
                "purpose": None,
                "metadata": {"i": i},
                "user_id": owner,
                "created_at": now,
            },
        )
    first, total = await call(db.get_products, user_id="alice", limit=2, page=1)
    second, second_total = await call(db.get_products, user_id="alice", limit=2, page=2)
    assert total == second_total == 3
    assert [r["id"] for r in first + second] == ["4", "2", "0"]
    assert (await call(db.get_products, user_id="absent")) == ([], 0)
    assert (await call(db.get_products))[1] == 6
    assert await call(db.get_product, "3", user_id="alice") is None
    assert await call(db.delete_product, "4", user_id="alice")
    rows, total = await call(db.get_products, user_id="alice", limit=1)
    assert total == 2 and rows[0]["id"] == "2"
    rows, total = await call(db.get_products, user_id="alice", limit=1, include_deleted=True)
    assert total == 3 and rows[0]["id"] == "4"


@pytest.mark.asyncio
async def test_validation_and_immutable_fields(db):
    m = manager(db)
    for name in [None, "", "   "]:
        with pytest.raises(ValueError):
            await call(m.create, name=name)
    for kwargs in [{"limit": 0}, {"page": 0}]:
        with pytest.raises(ValueError):
            await call(m.list, **kwargs)
        with pytest.raises(ValueError):
            await call(db.get_products, **kwargs)
    a = await call(m.create, name="SDK", user_id="alice")
    for fields in [
        {"id": "other"},
        {"created_at": 0},
        {"deleted_at": 1},
        {"updated_at": 0},
        {"name": None},
        {"metadata": []},
        {"purpose": {}},
    ]:
        with pytest.raises(ValueError):
            await call(m.update, a["id"], **fields)
        with pytest.raises(ValueError):
            await call(db.update_product, a["id"], **fields)
    assert await call(m.get, a["id"]) == {**a, "counts": EMPTY_COUNTS}


@pytest.mark.asyncio
async def test_custom_table_and_shared_schema_version(db):
    product = await call(manager(db).create, name="SDK")
    assert await call(db.table_exists, db.products_table_name)
    assert not await call(db.table_exists, "agno_company_products")
    assert await call(db.get_latest_schema_version, db.products_table_name)
    assert await call(db.get_product, product["id"]) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("loader", ["adapter", "resolver", "agent"])
async def test_configuration_roundtrip(db, loader):
    product = await call(manager(db).create, name="Roundtrip", user_id="alice")
    data = db.to_dict()
    assert data["products_table"] == db.products_table_name
    if loader == "adapter":
        reopened = type(db).from_dict(data)
    elif loader == "resolver":
        reopened = db_from_dict(data)
    else:
        reopened = Agent.from_dict(Agent(db=db, telemetry=False).to_dict()).db
    assert type(reopened) is type(db)
    try:
        assert reopened.products_table_name == db.products_table_name
        assert await call(reopened.get_product, product["id"], user_id="alice") == product
    finally:
        await call(reopened.close)


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", [False, True])
async def test_http_owner_isolation_and_override(db, tmp_path, isolation):
    from datetime import UTC, datetime, timedelta

    import jwt
    from httpx import ASGITransport, AsyncClient

    from agno.os import AgentOS, CompanyConfig
    from agno.os.config import AuthorizationConfig

    secret = "products-postgres-sqlite-parity-test"
    default = SqliteDb(db_file=str(tmp_path / "unused.db"))
    app = AgentOS(
        id="products-parity",
        db=default,
        company=CompanyConfig(db=db),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[secret], algorithm="HS256", user_isolation=isolation
        ),
    ).get_app()

    def headers(user):
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {
                    "sub": user,
                    "aud": "products-parity",
                    "scopes": ["products:read", "products:write", "products:delete"],
                    "exp": datetime.now(UTC) + timedelta(hours=1),
                },
                secret,
                algorithm="HS256",
            )
        }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/company/products", json={"name": "SDK", "user_id": "spoof"}, headers=headers("alice")
        )
        assert response.status_code == 201, response.text
        product = response.json()
        assert product["user_id"] == "alice"
        assert await call(db.get_product, product["id"]) is not None
        assert not default.table_exists(default.products_table_name)
        path = "/company/products/" + product["id"]
        # Products are shared regardless of isolation: scopes govern writes and the creator stays recorded.
        response = await client.get("/company/products?limit=1", headers=headers("bob"))
        assert response.json()["meta"]["total_count"] == 1
        assert (await client.get(path, headers=headers("bob"))).status_code == 200
        response = await client.patch(path, json={"purpose": "Updated"}, headers=headers("bob"))
        assert response.status_code == 200, response.text
        assert response.json()["purpose"] == "Updated" and response.json()["user_id"] == "alice"
        assert (await client.delete(path, headers=headers("alice"))).status_code == 204
        assert (await client.get(path, headers=headers("alice"))).status_code == 404
        assert (await client.get(path + "?include_deleted=true", headers=headers("alice"))).status_code == 200
        assert (await client.post(path + "/restore", headers=headers("alice"))).status_code == 200
        assert (await client.post(path + "/restore", headers=headers("alice"))).status_code == 409
    default.close()
