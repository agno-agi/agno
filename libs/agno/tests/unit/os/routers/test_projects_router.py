"""Project HTTP lifecycle and persistence contracts, following Products."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def client(request, tmp_path):
    db = (AsyncSqliteDb if request.param else SqliteDb)(db_file=str(tmp_path / "work.db"))
    with TestClient(AgentOS(db=db, company=CompanyConfig(), telemetry=False).get_app()) as client:
        yield client
    if request.param:
        asyncio.run(db.close())
    else:
        db.close()


def create(client):
    parent = client.post("/company/products", json={"name": "SDK"}).json()["id"]
    response = client.post("/company/projects", json={"product_id": parent, "name": "Ship", "outcome": "Build"})
    assert response.status_code == 201, response.text
    return response.json()


def transition(client, path, target):
    body = {"target": target, "reason": "Reviewed"}
    if target == "ready":
        body.update(executor_type="agent", executor_id="writer")
    return client.post(path + "/transitions", json=body)


def test_lifecycle(client):
    record = create(client)
    path = "/company/projects/" + record["id"]
    assert record["status"] == "proposed"
    assert client.patch(path, json={"outcome": None}).status_code == 200
    assert transition(client, path, "done").status_code == 409
    states = ["active", "done"]
    for state in states:
        response = transition(client, path, state)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == state
    assert [x["target"] for x in response.json()["transitions"]] == states
    assert all(x["reason"] == "Reviewed" for x in response.json()["transitions"])
    assert transition(client, path, "cancelled").status_code == 409
    assert client.post(path + "/restore").status_code == 409
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert transition(client, path, "cancelled").status_code == 404
    assert client.get(path + "?include_deleted=true").json()["deleted_at"] is not None
    assert client.get("/company/projects").json()["meta"]["total_count"] == 0
    assert client.get("/company/projects?include_deleted=true").json()["meta"]["total_count"] == 1
    assert client.post(path + "/restore").json()["status"] == "done"


@pytest.mark.parametrize("states", [[], ["active"]])
def test_cancel_from_every_nonterminal_state(client, states):
    path = "/company/projects/" + create(client)["id"]
    for state in states:
        assert transition(client, path, state).status_code == 200
    assert transition(client, path, "cancelled").status_code == 200
    assert transition(client, path, "active").status_code == 409


@pytest.mark.parametrize("body", [{"status": "done"}, {"user_id": "spoof"}, {"created_at": 0}, {"name": " "}])
def test_no_lifecycle_or_identity_edits(client, body):
    path = "/company/projects/" + create(client)["id"]
    assert client.patch(path, json=body).status_code == 422


def test_missing_parent_and_invalid_transitions(client):
    assert client.post("/company/projects", json={"product_id": "missing", "name": "Work"}).status_code == 404
    path = "/company/projects/" + create(client)["id"]
    for body in [
        {"target": "cancelled"},
        {"target": "cancelled", "reason": " "},
        {"target": "unknown", "reason": "Why"},
    ]:
        assert client.post(path + "/transitions", json=body).status_code == 422
    assert client.get("/company/projects?limit=0").status_code == 422


def test_cross_product_status_pagination(client):
    records = [create(client) for _ in range(3)]
    path = "/company/projects/" + records[0]["id"]
    assert transition(client, path, "cancelled").status_code == 200
    pages = [
        client.get("/company/projects", params={"status": "proposed", "limit": 1, "page": page}).json()
        for page in [1, 2]
    ]
    assert all(p["meta"]["total_count"] == 2 for p in pages)
    assert {p["data"][0]["id"] for p in pages} == {r["id"] for r in records[1:]}
    assert (
        client.get("/company/projects", params={"product_id": records[0]["product_id"]}).json()["meta"]["total_count"]
        == 1
    )


@pytest.mark.parametrize("db", [None, InMemoryDb()])
def test_unsupported_database(db):
    c = TestClient(AgentOS(company=CompanyConfig(db=db), telemetry=False).get_app())
    for method, path, body in [
        ("get", "/company/projects", None),
        ("get", "/company/projects/missing", None),
        ("post", "/company/projects", {"product_id": "p", "name": "Work"}),
        ("patch", "/company/projects/missing", {"name": "Work"}),
        ("delete", "/company/projects/missing", None),
        ("post", "/company/projects/missing/restore", None),
        ("post", "/company/projects/missing/transitions", {"target": "cancelled", "reason": "Stop"}),
    ]:
        assert c.request(method, path, json=body).status_code == 503
