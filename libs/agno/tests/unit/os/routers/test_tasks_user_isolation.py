"""JWT-backed Task scope and owner-isolation tests."""

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.config import AuthorizationConfig
from agno.team import Team
from agno.workflow import Workflow
from tests.unit.os.routers.test_tasks_router import reserve_run

SECRET = "company-tasks-isolation-tests"
OS_ID = "company-tasks-tests"
ALL_SCOPES = ["tasks:read", "tasks:write", "tasks:delete"]


def headers(user, scopes=None):
    token = jwt.encode(
        {
            "sub": user,
            "aud": OS_ID,
            "scopes": ALL_SCOPES if scopes is None else scopes,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def make_client(request, tmp_path):
    dbs = []

    def make(isolation):
        cls = AsyncSqliteDb if request.param else SqliteDb
        db = cls(db_file=str(tmp_path / (str(len(dbs)) + ".db")))
        dbs.append(db)
        client = TestClient(
            AgentOS(
                agents=[Agent(id="writer")],
                teams=[Team(id="writer", members=[])],
                workflows=[Workflow(id="writer", steps=[])],
                id=OS_ID,
                db=db,
                company=CompanyConfig(),
                telemetry=False,
                authorization=True,
                authorization_config=AuthorizationConfig(
                    verification_keys=[SECRET], algorithm="HS256", user_isolation=isolation
                ),
            ).get_app()
        )
        client.app.state.task_test_db = db
        return client

    yield make
    for db in dbs:
        if request.param:
            asyncio.run(db.close())
        else:
            db.close()


def create(client, user):
    parent = client.post("/company/products", json={"name": user}, headers=headers(user, ["products:write"])).json()[
        "id"
    ]
    project = client.post(
        "/company/projects", json={"product_id": parent, "name": "Release"}, headers=headers(user, ["projects:write"])
    ).json()
    response = client.post(
        "/company/tasks", json={"title": user, "product_id": parent, "project_id": project["id"]}, headers=headers(user)
    )
    assert response.status_code == 201, response.text
    assert response.json()["user_id"] == user
    return response.json()["id"]


def test_isolation_off_allows_scoped_readers_and_writers(make_client):
    c = make_client(False)
    a, b = create(c, "alice"), create(c, "bob")
    read = headers("reader", ["tasks:read"])
    assert {p["id"] for p in c.get("/company/tasks", headers=read).json()["data"]} == {a, b}
    assert c.get("/company/tasks/" + a, headers=read).status_code == 200
    path = "/company/tasks/" + a
    assert c.patch(path, json={"brief": "Updated"}, headers=headers("bob")).status_code == 200
    assert c.get(path, headers=read).json()["user_id"] == "alice"
    assert c.delete(path, headers=headers("bob")).status_code == 204
    assert c.post(path + "/restore", headers=headers("bob")).status_code == 200


def test_isolation_on_shares_reads_edits_and_deletion(make_client):
    c = make_client(True)
    a = create(c, "alice")
    own = {create(c, "bob") for _ in range(3)}
    pages = [
        c.get("/company/tasks", params={"status": "backlog", "limit": 2, "page": p}, headers=headers("bob")).json()
        for p in (1, 2)
    ]
    assert [len(p["data"]) for p in pages] == [2, 2]
    assert all(p["meta"]["total_count"] == 4 for p in pages)
    assert {row["id"] for p in pages for row in p["data"]} == own | {a}
    path = "/company/tasks/" + a
    before = c.get(path, headers=headers("alice")).json()
    assert c.get(path, headers=headers("bob")).json() == before
    edited = c.patch(path, json={"title": "Collaborative work"}, headers=headers("bob", ["tasks:write"]))
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Collaborative work"
    assert edited.json()["user_id"] == "alice"
    # Archive and restore need the scope, not ownership; the creator stays recorded.
    assert c.delete(path, headers=headers("bob")).status_code == 204
    assert c.get(path + "?include_deleted=true", headers=headers("bob")).status_code == 200
    assert c.get("/company/tasks?include_deleted=true", headers=headers("bob")).json()["meta"]["total_count"] == 4
    assert c.post(path + "/restore", headers=headers("bob")).status_code == 200
    assert c.get(path, headers=headers("alice")).json()["user_id"] == "alice"


def test_admin_bypass_and_creator_attribution(make_client):
    c = make_client(True)
    a = create(c, "alice")
    admin = headers("admin", ["agent_os:admin"])
    path = "/company/tasks/" + a
    assert c.get(path, headers=admin).status_code == 200
    assert c.patch(path, json={"title": "renamed"}, headers=admin).status_code == 200
    assert c.delete(path, headers=admin).status_code == 204
    assert c.post(path + "/restore", headers=admin).status_code == 200
    parent = c.post("/company/products", json={"name": "Admin product"}, headers=admin).json()["id"]
    project = c.post("/company/projects", json={"name": "Admin project", "product_id": parent}, headers=admin).json()
    response = c.post(
        "/company/tasks", json={"title": "Admin work", "product_id": parent, "project_id": project["id"]}, headers=admin
    )
    assert response.status_code == 201
    assert response.json()["user_id"] == "admin"


@pytest.mark.parametrize("isolation", [False, True])
def test_scopes_apply_to_every_route(make_client, isolation):
    c = make_client(isolation)
    path = "/company/tasks/" + create(c, "alice")
    for method, url, body, scopes in [
        ("get", "/company/tasks", None, ["tasks:write"]),
        ("get", path, None, ["tasks:write"]),
        ("post", "/company/tasks", {"name": "No"}, ["tasks:read"]),
        ("patch", path, {"name": "No"}, ["tasks:read"]),
        ("delete", path, None, ["tasks:write"]),
        ("post", path + "/restore", None, ["tasks:write"]),
        ("post", path + "/transitions", {"target": "cancelled", "reason": "Stop"}, ["tasks:read"]),
    ]:
        assert c.request(method, url, json=body, headers=headers("bob", scopes)).status_code == 403
    assert c.get("/company/tasks").status_code == 401


@pytest.mark.parametrize("authorization", [False, True])
def test_service_account_scopes_on_company_routes(tmp_path, authorization):
    import time

    from agno.company import CompanyManager
    from agno.os.service_accounts import generate_token

    db = SqliteDb(db_file=str(tmp_path / "service-accounts.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Shared product", user_id="alice")
    project = manager.create_project(product_id=product["id"], name="Release", user_id="alice")
    shared = manager.create_task(
        product_id=product["id"], title="Shared work", project_id=project["id"], user_id="alice"
    )
    token, token_hash, token_prefix = generate_token()
    db.create_service_account(
        {
            "id": "reader-id",
            "name": "reader",
            "user_id": "admin",
            "token_hash": token_hash,
            "token_prefix": token_prefix,
            "scopes": ["tasks:read"],
            "created_at": int(time.time()),
            "expires_at": None,
            "last_used_at": None,
            "revoked_at": None,
            "created_by": "admin",
        }
    )
    app = AgentOS(
        agents=[Agent(id="writer")],
        teams=[Team(id="writer", members=[])],
        workflows=[Workflow(id="writer", steps=[])],
        id=OS_ID,
        db=db,
        company=CompanyConfig(),
        telemetry=False,
        authorization=authorization,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256")
        if authorization
        else None,
    ).get_app()
    client = TestClient(app)
    auth = {"Authorization": "Bearer " + token}
    assert client.get("/company/tasks", headers=auth).status_code == 200
    assert client.get("/company/tasks/" + shared["id"], headers=auth).status_code == 200
    assert client.get("/company/tasks", headers=auth).json()["data"][0]["id"] == shared["id"]
    assert client.post("/company/tasks", json={"name": "Forbidden"}, headers=auth).status_code == 403
    assert client.patch("/company/tasks/missing", json={"name": "Forbidden"}, headers=auth).status_code == 403
    assert client.delete("/company/tasks/missing", headers=auth).status_code == 403
    assert client.post("/company/tasks/missing/restore", headers=auth).status_code == 403
    db.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_task_scopes_catalog_is_opt_in(enabled, tmp_path):
    from unittest.mock import MagicMock

    from agno.os.authz.admin_router import get_roles_router

    router = get_roles_router(MagicMock())
    db = SqliteDb(db_file=str(tmp_path / "catalog.db"))
    app = AgentOS(
        agents=[Agent(id="writer")],
        teams=[Team(id="writer", members=[])],
        workflows=[Workflow(id="writer", steps=[])],
        db=db,
        company=CompanyConfig() if enabled else None,
        telemetry=False,
    ).get_app()
    app.dependency_overrides[router.dependencies[0].dependency] = lambda: "admin"
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/authz/scopes")
    assert response.status_code == 200
    tasks = {item["raw"] for item in response.json() if item["namespace"] == "tasks"}
    assert tasks == (set(ALL_SCOPES) if enabled else set())


@pytest.mark.parametrize("kind,scope", [("agent", "agents"), ("team", "teams"), ("workflow", "workflows")])
@pytest.mark.parametrize("isolation", [False, True])
def test_ready_requires_accepting_callers_executor_scope(make_client, kind, scope, isolation):
    c = make_client(isolation)
    path = "/company/tasks/" + create(c, "alice")
    body = {"target": "ready", "reason": "Accept", "executor_type": kind, "executor_id": "writer"}
    for scopes in [["tasks:write"], ["tasks:write", scope + ":other:run"], ["tasks:read", scope + ":run"]]:
        assert c.post(path + "/transitions", json=body, headers=headers("bob", scopes)).status_code == 403
    assert c.get(path, headers=headers("alice")).json()["status"] == "backlog"
    accepted = c.post(path + "/transitions", json=body, headers=headers("bob", ["tasks:write", scope + ":writer:run"]))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted_by"] == "bob"
    assert accepted.json()["executor_id"] == "writer"
    assert isinstance(accepted.json()["accepted_at"], int)


def test_retired_executor_is_invalid_even_for_admin(make_client):
    c = make_client(False)
    path = "/company/tasks/" + create(c, "alice")
    body = {"target": "ready", "reason": "Accept", "executor_type": "engineering", "executor_id": "codex"}
    assert (
        c.post(path + "/transitions", json=body, headers=headers("alice", ["tasks:write", "agents:run"])).status_code
        == 422
    )
    assert c.post(path + "/transitions", json=body, headers=headers("admin", ["agent_os:admin"])).status_code == 422


def test_private_manager_members_cannot_be_accepted(make_client):
    from agno.registry._reserved import RESERVED_MEMBER_IDS

    c = make_client(False)
    path = "/company/tasks/" + create(c, "alice")
    for member in RESERVED_MEMBER_IDS:
        body = {"target": "ready", "reason": "Accept", "executor_type": "agent", "executor_id": member}
        response = c.post(path + "/transitions", json=body, headers=headers("admin", ["agent_os:admin"]))
        assert response.status_code == 409
        assert "Task executor" in response.json()["detail"]
        assert "Schedule" not in response.json()["detail"]


@pytest.mark.asyncio
async def test_acceptance_uses_provider_when_token_scopes_are_not_authoritative(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from fastapi import FastAPI, HTTPException
    from starlette.requests import Request

    from agno.os.routers.company.tasks import _require_endpoint_permission

    app = FastAPI()
    request = Request({"type": "http", "app": app})
    request.state.authorization_enabled = True
    request.state.user_id = "alice"
    request.state.scopes = ["agent_os:admin"]
    provider = Mock()
    monkeypatch.setattr("agno.os.auth.caller_scopes_are_authoritative", lambda request: False)
    monkeypatch.setattr("agno.os.auth.resolve_authorization_provider", lambda request: provider)
    provider.acheck = AsyncMock(return_value=False)
    with pytest.raises(HTTPException) as exc:
        await _require_endpoint_permission(request, "/agents/writer/runs", "POST")
    assert exc.value.status_code == 403
    ctx = provider.acheck.call_args.args[0]
    assert (ctx.principal_id, ctx.resource_type, ctx.resource_id, ctx.action) == ("alice", "agents", "writer", "run")
    provider.acheck.return_value = True
    await _require_endpoint_permission(request, "/agents/writer/runs", "POST")
    with pytest.raises(HTTPException) as exc:
        await _require_endpoint_permission(request, "/engineering/codex/runs", "POST")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_custom_admin_scope_is_respected():
    from fastapi import FastAPI, HTTPException
    from starlette.requests import Request

    from agno.os.routers.company.tasks import _require_endpoint_permission

    request = Request({"type": "http", "app": FastAPI()})
    request.state.authorization_enabled = True
    request.state.admin_scope = "custom:admin"
    request.state.scopes = ["agent_os:admin"]
    with pytest.raises(HTTPException):
        await _require_endpoint_permission(request, "/engineering/codex/runs", "POST")
    request.state.scopes = ["custom:admin"]
    await _require_endpoint_permission(request, "/engineering/codex/runs", "POST")


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["tasks", "schedules"])
async def test_run_target_permission_with_async_managed_roles(tmp_path, resource):
    from httpx import ASGITransport, AsyncClient

    from agno.os.authz import Authorization
    from agno.os.authz.native_engine import NativePolicyEngine

    db = AsyncSqliteDb(db_file=str(tmp_path / "managed.db"))
    engine = NativePolicyEngine(db=db)
    scopes = ["projects:write", "products:write", "tasks:read", "tasks:write", "schedules:write", "agents:writer:run"]
    await engine.aset_role_scopes("editor", [(scope, "allow") for scope in scopes])
    await engine.aassign("alice", "editor")
    app = AgentOS(
        agents=[Agent(id="writer")],
        teams=[Team(id="writer", members=[])],
        workflows=[Workflow(id="writer", steps=[])],
        id=OS_ID,
        db=db,
        company=CompanyConfig(),
        telemetry=False,
        authorization=Authorization(
            db=db, roles_claim="roles", verification_keys=[SECRET], algorithm="HS256", audience=OS_ID
        ),
    ).get_app()
    # Token admin claims must not override the stored executor permissions.
    auth = headers("alice", ["agent_os:admin"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            if resource == "tasks":
                product = await client.post("/company/products", json={"name": "SDK"}, headers=auth)
                assert product.status_code == 201, product.text
                project = await client.post(
                    "/company/projects", json={"product_id": product.json()["id"], "name": "Release"}, headers=auth
                )
                assert project.status_code == 201, project.text
                task = await client.post(
                    "/company/tasks",
                    json={"product_id": product.json()["id"], "project_id": project.json()["id"], "title": "Work"},
                    headers=auth,
                )
                assert task.status_code == 201, task.text
                path = "/company/tasks/" + task.json()["id"]
                body = {"target": "ready", "reason": "Accept", "executor_type": "agent", "executor_id": "denied"}
                denied = await client.post(path + "/transitions", json=body, headers=auth)
                assert denied.status_code == 403, denied.text
                record = (await client.get(path, headers=auth)).json()
                assert record["status"] == "backlog" and record["accepted_by"] is None
                body["executor_id"] = "writer"
                accepted = await client.post(path + "/transitions", json=body, headers=auth)
                assert accepted.status_code == 200, accepted.text
                assert accepted.json()["accepted_by"] == "alice"
            else:
                body = {"name": "Managed", "cron_expr": "0 9 * * *", "endpoint": "/agents/denied/runs"}
                denied = await client.post("/schedules", json=body, headers=auth)
                assert denied.status_code == 403, denied.text
                body["endpoint"] = "/agents/writer/runs"
                accepted = await client.post("/schedules", json=body, headers=auth)
                assert accepted.status_code == 201, accepted.text
    finally:
        await db.close()


@pytest.mark.parametrize("target", ["backlog", "cancelled"])
@pytest.mark.parametrize("start", ["ready", "in_progress", "in_review"])
def test_collaborators_return_or_cancel_accepted_tasks(make_client, start, target):
    c = make_client(True)
    path = "/company/tasks/" + create(c, "alice")
    writer = headers("bob", ["tasks:write"])
    accepted = c.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Accept", "executor_type": "agent", "executor_id": "writer"},
        headers=headers("bob", ["tasks:write", "agents:writer:run"]),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["accepted_by"] == "bob"
    assert accepted.json()["user_id"] == "alice"
    progress = {"ready": [], "in_progress": ["in_progress"], "in_review": ["in_progress", "in_review"]}
    for next_state in progress[start]:
        if next_state == "in_progress":
            reserve_run(c, path, user_id="bob")
            continue
        advanced = c.post(path + "/transitions", json={"target": next_state, "reason": "Progress"}, headers=writer)
        assert advanced.status_code == 200, advanced.text
    assert c.patch(path, json={"brief": "Changed"}, headers=writer).status_code == 409
    changed = c.post(path + "/transitions", json={"target": target, "reason": "Team decision"}, headers=writer)
    assert changed.status_code == 200, changed.text
    record = changed.json()
    assert record["status"] == target
    assert record["user_id"] == "alice"
    assert record["transitions"][-1]["user_id"] == "bob"
    if target == "backlog":
        assert all(record[key] is None for key in ("executor_type", "executor_id", "accepted_by", "accepted_at"))
        edited = c.patch(path, json={"brief": "Clarified scope"}, headers=writer)
        assert edited.status_code == 200
        assert edited.json()["brief"] == "Clarified scope"
    else:
        assert (
            c.post(path + "/transitions", json={"target": "backlog", "reason": "Reopen"}, headers=writer).status_code
            == 409
        )


@pytest.mark.parametrize(
    "targets", [["cancelled"], ["ready", "in_progress", "in_review", "in_progress", "in_review", "done"]]
)
def test_collaborators_complete_or_cancel_backlog_work(make_client, targets):
    c = make_client(True)
    path = "/company/tasks/" + create(c, "alice")
    for target in targets:
        if target == "in_progress":
            running = reserve_run(c, path, user_id="bob")
            assert running["user_id"] == "alice"
            assert running["transitions"][-1]["user_id"] == "bob"
            continue
        body = {"target": target, "reason": "Team decision"}
        if target == "ready":
            body.update(executor_type="agent", executor_id="writer")
        response = c.post(
            path + "/transitions", json=body, headers=headers("bob", ["tasks:write", "agents:writer:run"])
        )
        assert response.status_code == 200, response.text
        assert response.json()["user_id"] == "alice"
        assert response.json()["transitions"][-1]["user_id"] == "bob"
