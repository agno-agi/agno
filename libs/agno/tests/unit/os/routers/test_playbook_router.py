"""Manual playbook routes and Company database selection without a model."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig


@pytest.mark.parametrize("use_async", [False, True])
def test_company_database_override_is_used_without_os_model(tmp_path, use_async):
    cls = AsyncSqliteDb if use_async else SqliteDb
    primary = cls(db_file=str(tmp_path / "primary.db"))
    company = cls(db_file=str(tmp_path / "company.db"))
    os = AgentOS(db=primary, company=CompanyConfig(db=company), telemetry=False)
    with TestClient(os.get_app()) as client:
        assert client.post("/company/decisions", json={"decision": "company only"}).status_code == 201

    async def entries(db):
        return await db.get_learnings(namespace="company")

    if use_async:
        assert len(asyncio.run(entries(company))) == 1
        assert asyncio.run(entries(primary)) == []
        asyncio.run(primary.close())
        asyncio.run(company.close())
    else:
        assert len(company.get_learnings(namespace="company")) == 1
        assert primary.get_learnings(namespace="company") == []
        primary.close()
        company.close()


def test_playbook_without_database_reports_unavailable():
    os = AgentOS(company=CompanyConfig(), telemetry=False)
    with TestClient(os.get_app()) as client:
        assert client.get("/company/wiki").status_code == 503
        assert client.get("/company/decisions").status_code == 503
        assert client.post("/company/decisions", json={"decision": "manual"}).status_code == 503


def test_unsupported_wiki_database_reports_unavailable():
    from agno.db.in_memory import InMemoryDb

    os = AgentOS(company=CompanyConfig(db=InMemoryDb()), telemetry=False)
    with TestClient(os.get_app()) as client:
        assert client.get("/company/wiki").status_code == 503


@pytest.mark.parametrize("use_async", [False, True])
def test_company_wiki_cannot_be_redirected_by_product_query(tmp_path, use_async):
    cls = AsyncSqliteDb if use_async else SqliteDb
    db = cls(db_file=str(tmp_path / "wiki.db"))
    os = AgentOS(db=db, company=CompanyConfig(), telemetry=False)
    with TestClient(os.get_app()) as client:
        product = client.post("/company/products", json={"name": "SDK"}).json()
        product_url = "/company/products/" + product["id"] + "/wiki"
        original = client.get(product_url + "/status.md").json()
        company = client.get("/company/wiki/status.md").json()
        query = "?product_id=" + product["id"]
        assert client.get("/company/wiki/status.md" + query).json() == company
        assert client.get("/company/wiki" + query).json() == client.get("/company/wiki").json()
        assert (
            client.put(
                "/company/wiki/status.md" + query,
                json={"content": "Company only", "expected_version": company["metadata"]["version"]},
            ).status_code
            == 200
        )
        assert client.get(product_url + "/status.md").json() == original
        assert client.get("/company/wiki/status.md").json()["content"] == "Company only"
        paths = client.get("/openapi.json").json()["paths"]
        for route, methods in paths.items():
            if route.startswith("/company/wiki"):
                for operation in methods.values():
                    assert all(param["name"] != "product_id" for param in operation.get("parameters", []))
    asyncio.run(db.close()) if use_async else db.close()
