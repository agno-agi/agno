"""Task HTTP lifecycle and persistence contracts, following Products."""

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.config import AuthorizationConfig
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
    client.post("/company/projects/" + project["id"] + "/transitions", json={"target": "active", "reason": "Approved"})
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


def test_cancelled_project_allows_task_cancellation_but_not_restart_over_http(client):
    product_id = client.post("/company/products", json={"name": "Rejected plan"}).json()["id"]
    project = client.post("/company/projects", json={"product_id": product_id, "name": "Draft"}).json()
    task = client.post(
        "/company/tasks", json={"product_id": product_id, "project_id": project["id"], "title": "Work"}
    ).json()
    response = client.post(
        f"/company/projects/{project['id']}/transitions", json={"target": "cancelled", "reason": "Reject"}
    )
    assert response.status_code == 200, response.text

    response = transition(client, "/company/tasks/" + task["id"], "cancelled")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"
    response = transition(client, "/company/tasks/" + task["id"], "ready")
    assert response.status_code == 409
    assert "cancelled Project" in response.json()["detail"]
    stored = client.get("/company/tasks/" + task["id"]).json()
    assert stored["status"] == "cancelled"
    assert [entry["target"] for entry in stored["transitions"]] == ["cancelled"]


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
    assert transition(client, path, "done").status_code == 409
    assert client.post(path + "/restore").status_code == 409
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert transition(client, path, "cancelled").status_code == 404
    assert client.get(path + "?include_deleted=true").json()["deleted_at"] is not None
    assert client.get("/company/tasks").json()["meta"]["total_count"] == 0
    assert client.get("/company/tasks?include_deleted=true").json()["meta"]["total_count"] == 1
    assert client.post(path + "/restore").json()["status"] == "done"


def test_archive_lifecycle(client):
    record = create(client)
    path = "/company/tasks/" + record["id"]
    assert client.post("/company/tasks/missing/archive").status_code == 404
    archived = client.post(path + "/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["id"] == record["id"]
    assert isinstance(archived.json()["deleted_at"], int)
    assert client.get(path).status_code == 404
    assert client.get(path, params={"include_deleted": True}).json() == archived.json()
    assert client.post(path + "/archive").status_code == 404
    restored = client.post(path + "/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None


@pytest.mark.parametrize("parent", ["product", "project"])
def test_archive_parent_with_active_task_refused(client, parent):
    task = create(client)
    assert transition(client, "/company/tasks/" + task["id"], "ready").status_code == 200
    response = client.post(f"/company/{parent}s/{task[parent + '_id']}/archive")
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "message": "Cannot archive with active Tasks",
        "tasks": [{"id": task["id"], "title": "Ship"}],
    }
    assert client.get("/company/products/" + task["product_id"]).status_code == 200
    assert client.get("/company/projects/" + task["project_id"]).status_code == 200
    assert client.get("/company/tasks/" + task["id"]).json()["status"] == "ready"


def test_archive_product_cascades_and_restores(client):
    task = create(client)
    project_path = "/company/projects/" + task["project_id"]
    task_path = "/company/tasks/" + task["id"]
    product_path = "/company/products/" + task["product_id"]
    assert client.post(product_path + "/archive").status_code == 200
    assert client.get(project_path).status_code == 404
    assert client.get(task_path).status_code == 404
    assert client.post(product_path + "/restore").status_code == 200
    assert client.get(project_path).status_code == 200
    assert client.get(task_path).json()["status"] == "backlog"


def test_bulk_archive_reports_each_task(client):
    a, b, c = (create(client)["id"] for _ in range(3))
    assert client.post("/company/tasks/" + c + "/archive").status_code == 200
    response = client.post("/company/tasks/archive", json={"task_ids": [a, "missing", c, b, a]})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "results": [
            {"id": a, "status_code": 200, "detail": None},
            {"id": "missing", "status_code": 404, "detail": "Task not found"},
            {"id": c, "status_code": 404, "detail": "Task not found"},
            {"id": b, "status_code": 200, "detail": None},
        ]
    }
    for task_id in [a, b]:
        path = "/company/tasks/" + task_id
        assert client.get(path).status_code == 404
        assert isinstance(client.get(path, params={"include_deleted": True}).json()["deleted_at"], int)


def test_bulk_archive_validates_before_archiving(client):
    task_id = create(client)["id"]
    for body in [{"task_ids": []}, {"task_ids": [task_id], "force": True}]:
        assert client.post("/company/tasks/archive", json=body).status_code == 422
    assert client.get("/company/tasks/" + task_id).json()["deleted_at"] is None


@pytest.mark.parametrize("parent", ["product", "project"])
def test_bulk_archive_reports_a_refused_parent(client, parent):
    blocked, free = create(client), create(client)
    assert transition(client, "/company/tasks/" + blocked["id"], "ready").status_code == 200
    x, y = blocked[parent + "_id"], free[parent + "_id"]
    response = client.post(f"/company/{parent}s/archive", json={parent + "_ids": [x, y]})
    assert response.status_code == 200, response.text
    assert response.json()["results"] == [
        {
            "id": x,
            "status_code": 409,
            "detail": {
                "message": "Cannot archive with active Tasks",
                "tasks": [{"id": blocked["id"], "title": "Ship"}],
            },
        },
        {"id": y, "status_code": 200, "detail": None},
    ]
    assert client.get(f"/company/{parent}s/{x}").status_code == 200
    assert client.get("/company/tasks/" + blocked["id"]).json()["status"] == "ready"
    assert client.get(f"/company/{parent}s/{y}").status_code == 404
    assert client.get("/company/tasks/" + free["id"]).status_code == 404


def test_bulk_archive_stops_at_a_server_error(client, monkeypatch):
    a, b, c = (create(client)["id"] for _ in range(3))
    db = client.app.state.task_test_db
    delete_task = db.delete_task

    def fail_for_b(task_id, *args, **kwargs):
        # Raised on the call, before an async database creates its coroutine, so both managers see it.
        if task_id == b:
            raise NotImplementedError
        return delete_task(task_id, *args, **kwargs)

    monkeypatch.setattr(db, "delete_task", fail_for_b)
    body = {"task_ids": [a, b, c]}
    response = client.post("/company/tasks/archive", json=body)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Company tasks not supported by the configured database"
    assert client.get("/company/tasks/" + a).status_code == 404
    assert [client.get("/company/tasks/" + task_id).json()["deleted_at"] for task_id in [b, c]] == [None, None]
    monkeypatch.undo()
    response = client.post("/company/tasks/archive", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["results"] == [
        {"id": a, "status_code": 404, "detail": "Task not found"},
        {"id": b, "status_code": 200, "detail": None},
        {"id": c, "status_code": 200, "detail": None},
    ]


def test_apply_each_reports_an_empty_answer_as_204():
    from agno.os.routers.company.tasks import _apply_each

    async def route(record_id):
        return None

    assert asyncio.run(_apply_each(["a", "a"], route)) == {"results": [{"id": "a", "status_code": 204, "detail": None}]}


@pytest.mark.parametrize("states", [[], ["ready"], ["ready", "in_progress"], ["ready", "in_progress", "in_review"]])
def test_cancel_from_every_nonterminal_state(client, states):
    path = "/company/tasks/" + create(client)["id"]
    for state in states:
        if state == "in_progress":
            reserve_run(client, path)
            continue
        assert transition(client, path, state).status_code == 200
    assert transition(client, path, "cancelled").status_code == 200
    assert transition(client, path, "ready").status_code == 200


def test_create_in_status(client):
    parent = client.post("/company/products", json={"name": "SDK"}).json()["id"]
    project = client.post("/company/projects", json={"product_id": parent, "name": "Release"}).json()["id"]
    client.post("/company/projects/" + project + "/transitions", json={"target": "active", "reason": "Approved"})
    body = {"product_id": parent, "project_id": project, "title": "Ship"}
    ready = client.post(
        "/company/tasks", json={**body, "status": "ready", "executor_type": "agent", "executor_id": "writer"}
    )
    assert ready.status_code == 201, ready.text
    assert ready.json()["status"] == "ready"
    assert ready.json()["executor_id"] == "writer"
    assert [x["target"] for x in ready.json()["transitions"]] == ["ready"]
    assert client.post("/company/tasks", json={**body, "status": "cancelled"}).json()["status"] == "cancelled"
    assert client.post("/company/tasks", json={**body, "status": "ready"}).status_code == 422
    assert client.post("/company/tasks", json={**body, "status": "in_progress"}).status_code == 422


def test_reopen_finished_work(client):
    record = create(client)
    path = "/company/tasks/" + record["id"]
    transition(client, path, "ready")
    reserve_run(client, path)
    for state in ["in_review", "done", "backlog", "ready"]:
        assert transition(client, path, state).status_code == 200
    assert transition(client, path, "done").status_code == 200
    project = "/company/projects/" + record["project_id"]
    assert client.post(project + "/transitions", json={"target": "done", "reason": "Shipped"}).status_code == 200
    response = transition(client, path, "backlog")
    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot add open work to a completed or cancelled Project"


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


def test_allowed_transitions_follow_the_transition_rules(client):
    task = create(client)
    path = "/company/tasks/" + task["id"]
    assert task["last_run"] is None
    moves = {option["target"]: option for option in task["allowed_transitions"]}
    assert moves["ready"]["allowed"] and moves["cancelled"]["allowed"]
    # A direct start accepts a Backlog Task when the request names its executor.
    assert moves["in_progress"] == {"target": "in_progress", "allowed": True, "reason": None, "starts_run": True}
    blocked = client.post(path + "/transitions", json={"target": "in_review", "reason": "Skip"})
    assert blocked.status_code == 409 and blocked.json()["detail"] == moves["in_review"]["reason"]
    assert client.get(path).json()["allowed_transitions"] == task["allowed_transitions"]
    ready = transition(client, path, "ready").json()
    assert {option["target"]: option["allowed"] for option in ready["allowed_transitions"]}["in_progress"]


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
        ("post", "/company/tasks/missing/archive", None),
        ("post", "/company/tasks/missing/transitions", {"target": "cancelled", "reason": "Stop"}),
        ("post", "/company/tasks/archive", {"task_ids": ["missing"]}),
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
    assert client.patch(path, json={"executor_id": "other"}).status_code == 409
    assert client.patch(path, json={"brief": "Changed"}).status_code == 409
    assert client.patch(path, json={"title": "Renamed"}).json()["executor_id"] == "writer"
    assert transition(client, path, "backlog").status_code == 200
    backlog = client.get(path).json()
    assert all(backlog[key] is None for key in ["executor_type", "executor_id", "accepted_by", "accepted_at"])
    assert client.patch(path, json={"brief": "Changed"}).status_code == 200
    assert transition(client, path, "ready").status_code == 200
    assert transition(client, path, "in_progress").status_code == 409
    reserve_run(client, path)
    assert transition(client, path, "in_review").status_code == 200
    assert transition(client, path, "in_progress").status_code == 409


def walk_stages(client):
    """Yield (stage, path) while one Task advances to done, then a second one to cancelled."""
    path = "/company/tasks/" + create(client)["id"]
    yield "backlog", path
    for stage in ["ready", "in_progress", "in_review", "done"]:
        if stage == "in_progress":
            reserve_run(client, path)
        else:
            assert transition(client, path, stage).status_code == 200
        yield stage, path
    path = "/company/tasks/" + create(client)["id"]
    assert transition(client, path, "cancelled").status_code == 200
    yield "cancelled", path


def test_title_edits_at_every_stage_and_the_brief_and_structure_only_in_backlog(client):
    for stage, path in walk_stages(client):
        before = client.get(path).json()
        if stage == "backlog":
            edited = client.patch(path, json={"title": "Renamed " + stage, "brief": "Rewritten " + stage})
            assert edited.status_code == 200, (stage, edited.text)
            assert client.patch(path, json={"brief": "Brief only"}).json()["title"] == "Renamed " + stage
            assert client.patch(path, json={"brief": None}).json()["brief"] is None
            before = client.patch(path, json={"brief": "Accepted " + stage}).json()
        else:
            # The brief is part of what was accepted. It changes after a return to Backlog.
            for body in [{"brief": "Rewritten"}, {"brief": None}, {"title": "Mixed", "brief": "Rewritten"}]:
                assert client.patch(path, json=body).status_code == 409, (stage, body)
            assert client.get(path).json() == before
            edited = client.patch(path, json={"title": "Renamed " + stage, "brief": before["brief"]})
            assert edited.status_code == 200, (stage, edited.text)
        after = client.patch(path, json={"title": "Title only"}).json()
        assert after["title"] == "Title only"
        ignored = {"title", "brief", "updated_at"} if stage == "backlog" else {"title", "updated_at"}
        assert {k: v for k, v in after.items() if k not in ignored} == {
            k: v for k, v in before.items() if k not in ignored
        }
        assert client.patch(path, json={"title": " "}).status_code == 422
        snapshot = client.get(path).json()
        if stage == "backlog":
            continue
        for body in [
            {"executor_id": "other"},
            {"executor_type": "team"},
            {"evidence": [{"url": "https://example.test"}]},
        ]:
            assert client.patch(path, json=body).status_code == 409, (stage, body)
            assert client.patch(path, json={"title": "Mixed", **body}).status_code == 409, (stage, body)
        assert client.get(path).json() == snapshot
        assert client.patch(path, json={}).json() == snapshot


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
        {"target": "ready", "reason": "Accept", "executor_type": "agent"},
        {"target": "ready", "reason": "Accept", "executor_id": "a"},
        {"target": "ready", "reason": "Accept", "executor_type": "agent", "executor_id": " "},
        {"target": "cancelled", "reason": "Cancel", "executor_type": "agent", "executor_id": "a"},
        {"target": "ready", "reason": "Accept", "executor_type": "agent", "executor_id": "a", "accepted_by": "spoof"},
    ],
)
def test_invalid_acceptance(client, body):
    path = "/company/tasks/" + create(client)["id"]
    assert client.post(path + "/transitions", json=body).status_code == 422


def test_acceptance_with_no_executor_names_mini_agent_and_needs_it(client):
    # This deployment has no Company model, so Mini Agent does not exist.
    path = "/company/tasks/" + create(client)["id"]
    response = client.post(path + "/transitions", json={"target": "ready", "reason": "Accept"})
    assert response.status_code == 409 and "Mini Agent is unavailable" in response.text
    assert client.get(path).json()["status"] == "backlog"


def test_project_approval_keeps_ready_validation_and_permissions(client):
    product = client.post("/company/products", json={"name": "SDK"}).json()
    project = client.post("/company/projects", json={"product_id": product["id"], "name": "Release"}).json()
    body = dict(product_id=product["id"], project_id=project["id"], title="Ship", status="ready")
    missing_executor = client.post("/company/tasks", json=body)
    assert missing_executor.status_code == 422
    assert "executor" in missing_executor.text
    body.update(executor_type="agent", executor_id="writer")
    secret = "company-project-approval-test-signing-key"
    app = AgentOS(
        id="approval-tests",
        agents=[Agent(id="writer")],
        db=client.app.state.task_test_db,
        company=CompanyConfig(),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[secret], algorithm="HS256", user_isolation=False),
    ).get_app()
    with TestClient(app) as protected:
        for scopes, expected in [(["tasks:write"], 403), (["tasks:write", "agents:writer:run"], 422)]:
            token = jwt.encode(
                dict(
                    sub="reviewer",
                    aud="approval-tests",
                    scopes=scopes,
                    exp=datetime.now(timezone.utc) + timedelta(hours=1),
                    iat=datetime.now(timezone.utc),
                ),
                secret,
                algorithm="HS256",
            )
            headers = {"Authorization": "Bearer " + token}
            response = protected.post("/company/tasks", json=body, headers=headers)
            assert response.status_code == expected, response.text
            if expected == 422:
                assert response.json()["detail"] == (
                    "Project approval is required before creating Tasks outside Backlog or moving them to Ready"
                )
            assert client.get("/company/tasks").json()["meta"]["total_count"] == 0
        approved = client.post(
            "/company/projects/" + project["id"] + "/transitions", json={"target": "active", "reason": "Approved"}
        )
        assert approved.status_code == 200, approved.text
        created = protected.post("/company/tasks", json=body, headers=headers)
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "ready"


def test_proposed_project_allows_backlog_preview_but_not_acceptance(client):
    product = client.post("/company/products", json={"name": "SDK"}).json()
    project = client.post("/company/projects", json={"product_id": product["id"], "name": "Review"}).json()
    body = {"product_id": product["id"], "project_id": project["id"], "title": "Draft"}
    created = client.post("/company/tasks", json=body)
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "backlog" and task["accepted_at"] is None
    path = "/company/tasks/" + task["id"]
    before = client.get(path).json()
    refused = transition(client, path, "ready")
    assert refused.status_code == 409, refused.text
    assert client.get(path).json() == before
    assert client.get("/company/projects/" + project["id"]).json()["status"] == "proposed"
    approved = client.post(
        "/company/projects/" + project["id"] + "/transitions",
        json={"target": "active", "reason": "Approved"},
    )
    assert approved.status_code == 200, approved.text
    assert client.get(path).json() == before
    accepted = transition(client, path, "ready")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ready"
