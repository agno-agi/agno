"""Task HTTP lifecycle and persistence contracts, following Products."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.team import Team
from agno.workflow import Workflow


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def client(request, tmp_path):
    db = (AsyncSqliteDb if request.param else SqliteDb)(db_file=str(tmp_path / "work.db"))
    with TestClient(
        AgentOS(
            agents=[Agent(id="writer")],
            teams=[Team(id="writer", members=[])],
            workflows=[Workflow(id="writer", steps=[])],
            db=db,
            company=CompanyConfig(),
            telemetry=False,
        ).get_app()
    ) as client:
        client.app.state.task_test_db = db
        yield client
    if request.param:
        asyncio.run(db.close())
    else:
        db.close()


def create(client):
    parent = client.post("/company/products", json={"name": "SDK"}).json()["id"]
    project = client.post("/company/projects", json={"product_id": parent, "name": "Release"}).json()
    response = client.post(
        "/company/tasks", json={"product_id": parent, "project_id": project["id"], "title": "Ship", "brief": "Build"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def transition(client, path, target):
    body = {"target": target, "reason": "Reviewed"}
    if target == "ready":
        body.update(executor_type="agent", executor_id="writer")
    return client.post(path + "/transitions", json=body)


def reserve_run(client, path, user_id=None):
    """Seed a committed run reservation for route tests without a queue worker."""
    from agno.company.execution import _call

    async def reserve():
        db = client.app.state.task_test_db
        task_id = path.rsplit("/", 1)[-1]
        task = await _call(db, "get_task", task_id)
        attempt = max((entry.get("attempt", 0) for entry in task["transitions"]), default=0) + 1
        return await _call(db, "start_task_run", task_id, attempt, task["transitions"], user_id=user_id)

    return asyncio.run(reserve())


def test_lifecycle(client):
    record = create(client)
    path = "/company/tasks/" + record["id"]
    assert record["status"] == "backlog"
    assert client.patch(path, json={"brief": None}).status_code == 200
    assert transition(client, path, "done").status_code == 409
    states = ["ready", "in_progress", "in_review", "done"]
    for state in states:
        if state == "in_progress":
            assert transition(client, path, state).status_code == 409
            assert reserve_run(client, path)["status"] == state
            continue
        response = transition(client, path, state)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == state
    assert [x["target"] for x in response.json()["transitions"]] == states
    assert all(x["reason"] == "Reviewed" for x in response.json()["transitions"] if "attempt" not in x)
    assert response.json()["transitions"][1]["attempt"] == 1
    assert transition(client, path, "cancelled").status_code == 409
    assert client.post(path + "/restore").status_code == 409
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert transition(client, path, "cancelled").status_code == 404
    assert client.get(path + "?include_deleted=true").json()["deleted_at"] is not None
    assert client.get("/company/tasks").json()["meta"]["total_count"] == 0
    assert client.get("/company/tasks?include_deleted=true").json()["meta"]["total_count"] == 1
    assert client.post(path + "/restore").json()["status"] == "done"


@pytest.mark.parametrize("states", [[], ["ready"], ["ready", "in_progress"], ["ready", "in_progress", "in_review"]])
def test_cancel_from_every_nonterminal_state(client, states):
    path = "/company/tasks/" + create(client)["id"]
    for state in states:
        if state == "in_progress":
            reserve_run(client, path)
            continue
        assert transition(client, path, state).status_code == 200
    assert transition(client, path, "cancelled").status_code == 200
    assert transition(client, path, "ready").status_code == 409


@pytest.mark.parametrize("body", [{"status": "done"}, {"user_id": "spoof"}, {"created_at": 0}, {"title": " "}])
def test_no_lifecycle_or_identity_edits(client, body):
    path = "/company/tasks/" + create(client)["id"]
    assert client.patch(path, json=body).status_code == 422


def test_missing_parent_and_invalid_transitions(client):
    assert (
        client.post(
            "/company/tasks", json={"product_id": "missing", "project_id": "missing", "title": "Work"}
        ).status_code
        == 404
    )
    path = "/company/tasks/" + create(client)["id"]
    for body in [
        {"target": "cancelled"},
        {"target": "cancelled", "reason": " "},
        {"target": "unknown", "reason": "Why"},
    ]:
        assert client.post(path + "/transitions", json=body).status_code == 422
    assert client.get("/company/tasks?limit=0").status_code == 422


def test_cross_product_status_pagination(client):
    records = [create(client) for _ in range(3)]
    path = "/company/tasks/" + records[0]["id"]
    assert transition(client, path, "cancelled").status_code == 200
    pages = [
        client.get("/company/tasks", params={"status": "backlog", "limit": 1, "page": page}).json() for page in [1, 2]
    ]
    assert all(p["meta"]["total_count"] == 2 for p in pages)
    assert {p["data"][0]["id"] for p in pages} == {r["id"] for r in records[1:]}
    assert (
        client.get("/company/tasks", params={"product_id": records[0]["product_id"]}).json()["meta"]["total_count"] == 1
    )


@pytest.mark.parametrize("db", [None, InMemoryDb()])
def test_unsupported_database(db):
    c = TestClient(
        AgentOS(
            agents=[Agent(id="writer")],
            teams=[Team(id="writer", members=[])],
            workflows=[Workflow(id="writer", steps=[])],
            company=CompanyConfig(db=db),
            telemetry=False,
        ).get_app()
    )
    for method, path, body in [
        ("get", "/company/tasks", None),
        ("get", "/company/runs/missing", None),
        ("post", "/company/runs/missing/cancel", None),
        ("get", "/company/tasks/missing", None),
        ("post", "/company/tasks", {"product_id": "p", "project_id": "p", "title": "Work"}),
        ("patch", "/company/tasks/missing", {"title": "Work"}),
        ("delete", "/company/tasks/missing", None),
        ("post", "/company/tasks/missing/restore", None),
        ("post", "/company/tasks/missing/transitions", {"target": "cancelled", "reason": "Stop"}),
    ]:
        response = c.request(method, path, json=body)
        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Company requires a database" if db is None else "Company tasks not supported by the configured database"
        )


def test_acceptance_freezes_scope_and_backlog_clears_it(client):
    task = create(client)
    path = "/company/tasks/" + task["id"]
    ready = transition(client, path, "ready").json()
    assert ready["executor_type"] == "agent" and ready["executor_id"] == "writer"
    assert isinstance(ready["accepted_at"], int)
    assert client.patch(path, json={"brief": "Changed"}).status_code == 409
    assert transition(client, path, "backlog").status_code == 200
    backlog = client.get(path).json()
    assert all(backlog[key] is None for key in ["executor_type", "executor_id", "accepted_by", "accepted_at"])
    assert client.patch(path, json={"brief": "Changed"}).status_code == 200
    assert transition(client, path, "ready").status_code == 200
    assert transition(client, path, "in_progress").status_code == 409
    reserve_run(client, path)
    assert transition(client, path, "in_review").status_code == 200
    assert transition(client, path, "in_progress").status_code == 409


def test_task_project_must_belong_to_same_product(client):
    task = create(client)
    other = create(client)
    project = client.post("/company/projects", json={"product_id": other["product_id"], "name": "Other"}).json()
    path = "/company/tasks/" + task["id"]
    assert client.patch(path, json={"project_id": project["id"]}).status_code == 422
    assert (
        client.post(
            "/company/tasks", json={"product_id": task["product_id"], "title": "Bad", "project_id": project["id"]}
        ).status_code
        == 422
    )
    assert client.patch(path, json={"project_id": "missing"}).status_code == 404
    own = client.post("/company/projects", json={"product_id": task["product_id"], "name": "Own"}).json()
    assert client.patch(path, json={"project_id": own["id"]}).status_code == 200
    assert client.get("/company/tasks", params={"project_id": own["id"]}).json()["meta"]["total_count"] == 1
    assert client.patch(path, json={"project_id": None}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"target": "ready", "reason": "Accept"},
        {"target": "ready", "reason": "Accept", "executor_type": "agent", "executor_id": " "},
        {"target": "cancelled", "reason": "Cancel", "executor_type": "agent", "executor_id": "a"},
        {"target": "ready", "reason": "Accept", "executor_type": "agent", "executor_id": "a", "accepted_by": "spoof"},
    ],
)
def test_invalid_acceptance(client, body):
    path = "/company/tasks/" + create(client)["id"]
    assert client.post(path + "/transitions", json=body).status_code == 422
