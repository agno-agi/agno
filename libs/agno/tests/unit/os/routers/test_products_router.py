"""Products HTTP behavior, assembly and unsupported database handling."""

import asyncio
import importlib
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from agno.company import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.routers.company.products import get_products_router
from agno.os.scopes import get_default_scope_mappings
from agno.os.settings import AgnoAPISettings


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def client(request, tmp_path):
    cls = AsyncSqliteDb if request.param else SqliteDb
    db = cls(db_file=str(tmp_path / "products.db"))
    app = AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()
    with TestClient(app) as client:
        yield client
    if request.param:
        asyncio.run(db.close())
    else:
        db.close()


def test_lifecycle(client):
    response = client.post("/company/products", json={"name": "SDK", "purpose": "Build", "metadata": {"a": [1]}})
    assert response.status_code == 201, response.text
    product = response.json()
    assert product["user_id"] is None
    assert isinstance(product["created_at"], int)
    path = "/company/products/" + product["id"]
    assert client.get(path).json() == product
    updated = client.patch(path, json={"purpose": None, "metadata": {"b": 2}})
    assert updated.status_code == 200
    assert updated.json()["purpose"] is None
    assert updated.json()["metadata"] == {"archive_window_days": 14, "b": 2}
    assert updated.json()["updated_at"] is not None
    assert client.patch(path, json={}).json() == updated.json()
    assert client.post(path + "/restore").status_code == 409
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.patch(path, json={"name": "Hidden"}).status_code == 404
    assert client.delete(path).status_code == 404
    deleted = client.get(path, params={"include_deleted": True}).json()
    assert isinstance(deleted["deleted_at"], int)
    assert client.get("/company/products").json()["meta"]["total_count"] == 0
    assert client.get("/company/products?include_deleted=true").json()["meta"]["total_count"] == 1
    restored = client.post(path + "/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert restored.json()["created_at"] == product["created_at"]


def test_pagination_and_duplicate_display_names(client):
    ids = {client.post("/company/products", json={"name": "SDK"}).json()["id"] for _ in range(3)}
    pages = [client.get("/company/products", params={"page": page, "limit": 2}).json() for page in (1, 2)]
    assert [len(p["data"]) for p in pages] == [2, 1]
    assert all(set(p) == {"data", "meta"} for p in pages)
    assert all(p["meta"]["total_count"] == 3 and p["meta"]["total_pages"] == 2 for p in pages)
    assert {row["id"] for p in pages for row in p["data"]} == ids
    assert client.get("/company/products?page=3&limit=2").json()["data"] == []


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "  "}, {"name": None}, {"name": "SDK", "metadata": []}])
def test_invalid_create(client, body):
    assert client.post("/company/products", json=body).status_code == 422


@pytest.mark.parametrize("body", [{"name": None}, {"name": ""}, {"name": "  "}, {"purpose": []}])
def test_invalid_update(client, body):
    product = client.post("/company/products", json={"name": "SDK"}).json()
    assert client.patch("/company/products/" + product["id"], json=body).status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=1001", "page=0"])
def test_invalid_pagination(client, query):
    assert client.get("/company/products?" + query).status_code == 422


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/company/products/missing", None),
        ("patch", "/company/products/missing", {"name": "SDK"}),
        ("delete", "/company/products/missing", None),
        ("post", "/company/products/missing/restore", None),
    ],
)
def test_missing(client, method, path, body):
    assert client.request(method, path, json=body).status_code == 404


def test_database_resolution_once_and_override(tmp_path):
    default = SqliteDb(db_file=str(tmp_path / "default.db"))
    override = SqliteDb(db_file=str(tmp_path / "override.db"))
    for os_db, configured, expected in [
        (default, None, default),
        (default, override, override),
        (None, override, override),
    ]:
        config = CompanyConfig(db=configured)
        agent_os = AgentOS(db=os_db, company=config, telemetry=False)
        config.db = SqliteDb(db_file=str(tmp_path / "later.db"))
        assert agent_os._company_db is expected
        client = TestClient(agent_os.get_app())
        response = client.post("/company/products", json={"name": "SDK"})
        assert response.status_code == 201
        assert expected.get_product(response.json()["id"]) is not None
        agent_os.resync(client.app)
        client.app.openapi_schema = None
        paths = {
            path: methods
            for path, methods in client.app.openapi()["paths"].items()
            if path.startswith("/company/products") and "/wiki" not in path
        }
        assert sum(len(methods) for methods in paths.values()) == 6
        assert client.get("/company/products").status_code == 200
    default.close()
    override.close()


@pytest.mark.parametrize("async_db", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("configuration", ["inherited", "shared", "override", "company_only"])
def test_company_database_closed_once_on_shutdown(tmp_path, monkeypatch, async_db, configuration):
    cls = AsyncSqliteDb if async_db else SqliteDb
    os_db = None if configuration == "company_only" else cls(db_file=str(tmp_path / "os.db"))
    company_db = os_db if configuration in {"inherited", "shared"} else cls(db_file=str(tmp_path / "company.db"))
    close_mocks = []
    for db in {id(db): db for db in (os_db, company_db) if db is not None}.values():
        close = AsyncMock(wraps=db.close) if async_db else MagicMock(wraps=db.close)
        monkeypatch.setattr(db, "close", close)
        close_mocks.append(close)
    config = CompanyConfig(db=None if configuration == "inherited" else company_db)
    with TestClient(AgentOS(db=os_db, company=config, telemetry=False).get_app()) as client:
        response = client.post("/company/products", json={"name": "SDK"})
        assert response.status_code == 201, response.text
        for close in close_mocks:
            close.assert_not_called()
    for close in close_mocks:
        close.assert_called_once_with()
        if async_db:
            close.assert_awaited_once_with()


def test_import_without_company_changes_no_routes_tables_or_scopes(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "disabled.db"))
    with TestClient(AgentOS(db=db, telemetry=False).get_app()) as client:
        paths = set(client.app.openapi()["paths"])
        tables = set(inspect(db.db_engine).get_table_names())
    mappings = get_default_scope_mappings()
    importlib.import_module("agno.company")
    with TestClient(AgentOS(db=db, telemetry=False).get_app()) as client:
        assert set(client.app.openapi()["paths"]) == paths
        assert set(inspect(db.db_engine).get_table_names()) == tables
        assert client.get("/company/products").status_code == 404
    assert "agno_company_products" not in tables
    assert not any(path.startswith("/company") for path in paths)
    assert get_default_scope_mappings() == mappings
    assert not any("products:" in scope for scopes in mappings.values() for scope in scopes)
    assert get_default_scope_mappings(company=True)["POST /company/products/*/restore"] == ["products:delete"]


@pytest.mark.parametrize("db", [None, InMemoryDb()])
def test_unavailable_database_all_routes(db):
    client = TestClient(AgentOS(company=CompanyConfig(db=db), telemetry=False).get_app())
    for method, path, body in [
        ("get", "/company/products", None),
        ("get", "/company/products/missing", None),
        ("post", "/company/products", {"name": "SDK"}),
        ("patch", "/company/products/missing", {"name": "SDK"}),
        ("delete", "/company/products/missing", None),
        ("post", "/company/products/missing/restore", None),
    ]:
        assert client.request(method, path, json=body).status_code == 503


def test_manager_unsupported():
    manager = CompanyManager(InMemoryDb())
    for fn, kwargs in [
        (manager.create, {"name": "SDK"}),
        (manager.list, {}),
        (manager.get, {"product_id": "id"}),
        (manager.update, {"product_id": "id"}),
        (manager.delete, {"product_id": "id"}),
        (manager.restore, {"product_id": "id"}),
    ]:
        with pytest.raises(NotImplementedError, match="Company products not supported"):
            fn(**kwargs)


@pytest.mark.asyncio
async def test_async_manager_unsupported():
    db = MagicMock(spec=AsyncBaseDb)
    # Exercise the inherited default methods rather than mocked support.
    for method in [
        "create_product",
        "get_product",
        "get_products",
        "update_product",
        "delete_product",
        "restore_product",
    ]:
        setattr(db, method, getattr(AsyncBaseDb, method).__get__(db))
    manager = AsyncCompanyManager(db)
    for fn, kwargs in [
        (manager.create, {"name": "SDK"}),
        (manager.list, {}),
        (manager.get, {"product_id": "id"}),
        (manager.update, {"product_id": "id"}),
        (manager.delete, {"product_id": "id"}),
        (manager.restore, {"product_id": "id"}),
    ]:
        with pytest.raises(NotImplementedError, match="Company products not supported"):
            await fn(**kwargs)


def test_sync_database_does_not_run_on_event_loop(tmp_path):
    class ThreadCheckingDb(SqliteDb):
        def get_products(self, **kwargs):
            with pytest.raises(RuntimeError, match="no running event loop"):
                asyncio.get_running_loop()
            assert threading.get_ident() != event_loop_thread[0]
            return super().get_products(**kwargs)

    event_loop_thread = []
    app = FastAPI()

    @app.middleware("http")
    async def record_thread(request, call_next):
        event_loop_thread[:] = [threading.get_ident()]
        return await call_next(request)

    db = ThreadCheckingDb(db_file=str(tmp_path / "thread.db"))
    app.include_router(get_products_router(db, AgnoAPISettings()))
    assert TestClient(app).get("/company/products").status_code == 200
