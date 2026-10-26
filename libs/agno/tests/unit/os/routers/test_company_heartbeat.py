"""Heartbeat routes consume scheduler behavior and preserve bounded authority."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company import Product
from agno.company.manager import CompanyManager
from agno.company.routines import _RoutineAuthorization, load_routine_skills
from agno.db.schemas.scheduler import Schedule
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.authz.run_context import restore_authorization
from agno.run.authorization import AUTHORIZATION_HEADER, authorization_scope
from agno.scheduler.executor import ScheduleExecutor


@pytest.fixture
def system(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    agent = Agent(id="reader", telemetry=False)
    os = AgentOS(db=db, agents=[agent], company=CompanyConfig(), telemetry=False)
    with TestClient(os.get_app()) as client:
        yield client, os, db
    db.close()


def test_routine_scheduler_wrappers(system):
    client, os, db = system
    product = client.post("/company/products", json={"name": "Docs"}).json()
    body = dict(
        product_id=product["id"],
        name="intake",
        template="intake",
        executor_type="agent",
        executor_id="reader",
        cron_expr="0 * * * *",
    )
    response = client.post("/company/routines", json=body)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["managed_by"] == "company"
    assert row["target_id"] == "reader"
    assert row["payload"]["metadata"] == {"product_id": product["id"], "template": "intake", "auto_accept": False}
    assert row["payload"]["message"].endswith(load_routine_skills().get_skill("intake").instructions)
    assert db.get_product(product["id"])["metadata"]["routine_ids"] == [row["id"]]
    path = "/company/routines/" + row["id"]
    assert client.post(path + "/pause").json()["enabled"] is False
    assert client.post(path + "/resume").json()["enabled"] is True
    assert client.patch(path, json={"instructions": "Check quietly"}).status_code == 200
    message = db.get_schedule(row["id"])["payload"]["message"]
    assert product["id"] in message and message.endswith("Check quietly")
    assert client.patch(path, json={"auto_accept": True}).status_code == 422
    assert client.get(path + "/runs").json()["meta"]["total_count"] == 0
    assert len(client.get("/company/routines").json()["data"]) == 1


def test_product_metadata_edits_keep_linked_routines(system):
    client, _, db = system
    product = client.post("/company/products", json={"name": "Docs", "metadata": {"team": "a"}}).json()
    routine = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"], name="intake", template="intake", executor_type="agent", executor_id="reader"
        ),
    ).json()
    path = "/company/products/" + product["id"]

    for metadata in ({"team": "b"}, {"team": "b", "routine_ids": []}, None):
        response = client.patch(path, json={"metadata": metadata})
        assert response.status_code == 200, response.text
        assert response.json()["metadata"]["routine_ids"] == [routine["id"]]
    assert db.get_product(product["id"])["metadata"]["routine_ids"] == [routine["id"]]


@pytest.mark.parametrize("use_async", [False, True])
def test_schedule_tools_refuse_company_routines(system, use_async):
    import asyncio

    from agno.registry import Registry
    from agno.tools.scheduler import SchedulerTools
    from agno.tools.studio import StudioTools

    client, _, db = system
    product = client.post("/company/products", json={"name": "Docs"}).json()
    routine = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"], name="intake", template="intake", executor_type="agent", executor_id="reader"
        ),
    ).json()
    scheduler = SchedulerTools(db=db)
    studio = StudioTools(registry=Registry(), db=db, schedules=True)

    def call(tool, name, *args, **kwargs):
        if use_async:
            return asyncio.run(getattr(tool, "a" + name)(*args, **kwargs))
        return getattr(tool, name)(*args, **kwargs)

    for name in ("disable_schedule", "delete_schedule", "enable_schedule"):
        assert json.loads(call(scheduler, name, routine["id"]))["error_type"] == "company_routine", name
    result = json.loads(call(studio, "update_schedule", routine["id"], message="Ignore the Product"))
    assert result["error"]["code"] == "company_routine"

    stored = db.get_schedule(routine["id"])
    assert stored["enabled"] is True and stored["next_run_at"] == routine["next_run_at"]
    assert stored["payload"] == routine["payload"]
    assert db.get_product(product["id"])["metadata"]["routine_ids"] == [routine["id"]]

    plain = db.create_schedule(
        Schedule(id="plain", name="plain", cron_expr="0 * * * *", endpoint="/agents/reader/runs").to_dict()
    )
    assert json.loads(call(scheduler, "disable_schedule", plain["id"]))["status"] == "disabled"


def test_routine_routes_hide_automation_and_report_missing_product(system):
    from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID

    client, _, db = system
    for identifier in (COMPANY_AUTOMATION_SCHEDULE_ID, "missing-product"):
        if db.get_schedule(identifier) is None:
            db.create_schedule(
                Schedule(
                    id=identifier,
                    name=identifier,
                    cron_expr="0 * * * *",
                    endpoint="/agents/reader/runs",
                    managed_by="company",
                    payload={"metadata": {}},
                ).to_dict()
            )
        path = "/company/routines/" + identifier
        responses = [
            client.patch(path, json={"instructions": "Updated"}),
            client.get(path),
            client.post(path + "/trigger"),
            client.post(path + "/pause"),
            client.post(path + "/resume"),
            client.get(path + "/runs"),
        ]
        expected = 404 if identifier == COMPANY_AUTOMATION_SCHEDULE_ID else 409
        for response in responses:
            assert response.status_code == expected, response.text
            if expected == 409:
                assert response.json()["detail"] == "Routine is missing its Product metadata"
    assert client.get("/company/routines").json()["data"] == []


@pytest.mark.parametrize("field,value", [("cron_expr", "bad cron"), ("timezone", "not/a/timezone")])
def test_invalid_setup_does_not_create_records(system, field, value):
    client, _, db = system
    routine = dict(name="intake", template="intake", executor_type="agent", executor_id="reader", cron_expr="0 * * * *")
    routine[field] = value
    response = client.post("/company/setup", json={"name": "Invalid", "routines": [routine]})
    assert response.status_code == 422
    assert db.get_products()[1] == 0


@pytest.mark.asyncio
async def test_summary_uses_telegram_interface_transport(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from agno.company.summary import adeliver_summary

    bot = SimpleNamespace(send_message=AsyncMock(), close_session=AsyncMock())
    factory = Mock(return_value=bot)
    monkeypatch.setattr("telebot.async_telebot.AsyncTeleBot", factory)
    interface = SimpleNamespace(type="telegram", token="configured-token")
    await adeliver_summary([interface], "telegram", "123", "Product report")
    factory.assert_called_once_with("configured-token")
    assert bot.send_message.await_args.args[:2] == (123, "Product report")
    bot.close_session.assert_awaited_once()


def test_sources_setup_restart_and_diagnostics(system, tmp_path, monkeypatch):
    client, os, db = system
    path = tmp_path / "readme.md"
    path.write_text("# Release\nNew capability.\n")
    body = {
        "name": "AgentOS",
        "sources": [{"type": "markdown", "reference": str(path), "credential_ref": "HEARTBEAT_TOKEN"}],
    }
    first = client.post("/company/setup", json=body)
    assert first.status_code == 201, first.text
    assert client.patch("/company/products/" + first.json()["id"], json={"name": "Human edit"}).status_code == 200
    client.post("/company/products", json={"name": "Later Product"}).raise_for_status()
    second = client.post("/company/setup", json=body)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["name"] == "Human edit"
    sources = client.get("/company/sources").json()["data"]
    assert len(sources) == 1
    manager = CompanyManager(db)
    monkeypatch.setenv("HEARTBEAT_TOKEN", "never-forward-this-value")
    evidence = manager.read_source(sources[0]["id"], "run-1")
    assert "never-forward-this-value" not in json.dumps(evidence)
    from agno.os.diagnostics import run_diagnostics

    assert next(c for c in run_diagnostics(os).checks if c.name == "env:HEARTBEAT_TOKEN").status == "PASS"
    monkeypatch.delenv("HEARTBEAT_TOKEN")
    assert next(c for c in run_diagnostics(os).checks if c.name == "env:HEARTBEAT_TOKEN").status == "FAIL"
    assert client.delete("/company/sources/" + sources[0]["id"]).status_code == 204
    assert client.get("/company/sources").json()["data"] == []
    assert client.post("/company/sources/" + sources[0]["id"] + "/restore").status_code == 200


@pytest.mark.asyncio
async def test_company_metadata_survives_executor_scrub(monkeypatch):
    executor = ScheduleExecutor(base_url="http://test", internal_service_token="test")
    captured = {}

    async def capture(client, url, headers, payload, resource_type, resource_id, timeout_seconds):
        captured.update(payload=payload, headers=headers)
        return {"status": "success"}

    monkeypatch.setattr(executor, "_get_client", AsyncMock())
    monkeypatch.setattr(executor, "_background_run", capture)
    metadata = {"product_id": "p", "template": "intake", "auto_accept": False, "agno_component_version": 99}
    schedule = Schedule(
        id="s",
        name="test",
        cron_expr="0 * * * *",
        endpoint="/agents/reader/runs",
        managed_by="company",
        payload={"message": "Check", "metadata": metadata},
    )
    await executor._call_endpoint(schedule)
    assert json.loads(captured["payload"]["metadata"]) == {
        k: v for k, v in metadata.items() if k != "agno_component_version"
    }
    authority = restore_authorization(None, json.loads(captured["headers"][AUTHORIZATION_HEADER]))
    assert isinstance(authority, _RoutineAuthorization)
    with pytest.raises(PermissionError, match="schedules"):
        authority.require("schedules", "write")
    with pytest.raises(PermissionError, match="schedules"):
        await authority.arequire("schedules", "write")


def test_routine_cannot_accept(system):
    _, _, db = system
    manager = CompanyManager(db)
    product = manager.create(name="Docs")
    project = manager.create_project(product_id=product["id"], name="Documentation")
    project = manager.create_project(product_id=product["id"], name="Release")
    task = manager.create_task(product_id=product["id"], title="Draft", project_id=project["id"])
    with authorization_scope(lambda: _RoutineAuthorization(None)):
        with pytest.raises(PermissionError, match="cannot accept"):
            manager.transition_task(
                task_id=task["id"], target="ready", reason="self approval", executor_type="agent", executor_id="reader"
            )
    assert manager.get_task(task["id"])["status"] == "backlog"


def test_yaml_and_code_rehydrate_without_reset(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "declare.db"))
    declaration = Product(name="SDK", purpose="Maintain SDK")
    os = AgentOS(db=db, company=CompanyConfig(products=[declaration]), telemetry=False)
    with TestClient(os.get_app()) as client:
        first = client.get("/company/products").json()["data"][0]
        client.patch("/company/products/" + first["id"], json={"purpose": "Human direction"})
    with TestClient(AgentOS(db=db, company=CompanyConfig(products=[declaration]), telemetry=False).get_app()) as client:
        rows = client.get("/company/products").json()["data"]
        assert len(rows) == 1
        assert rows[0]["purpose"] == "Human direction"
    config = tmp_path / "config.yaml"
    config.write_text("company:\n  products:\n    - name: SDK\n      purpose: stale declaration\n")
    with TestClient(AgentOS(db=db, config=str(config), telemetry=False).get_app()) as client:
        assert client.get("/company/products").json()["data"][0]["purpose"] == "Human direction"
    db.close()


@pytest.mark.parametrize("isolation", [False, True])
def test_sources_and_routines_need_scopes_not_ownership(tmp_path, isolation):
    from datetime import datetime, timedelta, timezone

    import jwt

    from agno.os.config import AuthorizationConfig

    secret = "heartbeat-isolation-secret"
    scopes = [
        "products:read",
        "products:write",
        "sources:read",
        "sources:write",
        "sources:delete",
        "routines:read",
        "routines:write",
        "schedules:read",
        "schedules:write",
        "agents:reader:run",
    ]

    def headers(user, granted=None):
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {
                    "sub": user,
                    "private_claim": "private-claim-" + user,
                    "aud": "heartbeat",
                    "scopes": scopes if granted is None else granted,
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                },
                secret,
                algorithm="HS256",
            )
        }

    db = SqliteDb(db_file=str(tmp_path / "isolated.db"))
    os = AgentOS(
        id="heartbeat",
        db=db,
        agents=[Agent(id="reader", telemetry=False)],
        company=CompanyConfig(),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[secret], algorithm="HS256", user_isolation=isolation
        ),
    )
    with TestClient(os.get_app()) as client:
        product = client.post("/company/products", headers=headers("alice"), json={"name": "Docs"}).json()
        body = {"product_id": product["id"], "type": "markdown", "reference": "/docs"}
        # Any member with the Source scopes may configure a reader on any Product.
        assert client.post("/company/sources", headers=headers("bob"), json=body).status_code == 201
        assert client.post("/company/sources", headers=headers("alice"), json=body).status_code == 201
        assert client.get("/company/sources", headers=headers("bob", ["sources:read"])).json()["data"]
        routine = {
            "product_id": product["id"],
            "name": "intake",
            "template": "intake",
            "executor_type": "agent",
            "executor_id": "reader",
            "cron_expr": "0 * * * *",
        }
        assert (
            client.post(
                "/company/routines",
                headers=headers("alice", [s for s in scopes if s != "schedules:write"]),
                json=routine,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/company/routines",
                headers=headers("alice", [s for s in scopes if s != "agents:reader:run"]),
                json=routine,
            ).status_code
            == 403
        )
        created = client.post("/company/routines", headers=headers("alice"), json=routine)
        assert created.status_code == 201
        routine_id = created.json()["id"]
        assert routine_id in {
            row["id"] for row in client.get("/company/routines", headers=headers("bob")).json()["data"]
        }
        path = "/company/routines/" + routine_id
        assert client.get(path, headers=headers("bob")).status_code == 200
        assert client.get(path + "/runs", headers=headers("bob")).status_code == 200
        assert client.get(path, headers=headers("bob", ["routines:read"])).status_code == 200
        for granted in (["routines:read"], ["schedules:read"]):
            denied = client.get(path + "/runs", headers=headers("bob", granted))
            assert denied.status_code == 403, denied.text
        db.create_schedule_run(
            {
                "id": "private-history",
                "schedule_id": routine_id,
                "status": "success",
                "attempt": 1,
                "created_at": 1,
                "triggered_at": 1,
                "output": {"content": "Execution diagnostics"},
            }
        )
        history = client.get(path + "/runs", headers=headers("bob", ["routines:read", "schedules:read"]))
        assert history.status_code == 200, history.text
        assert history.json()["data"][0]["output"] == {"content": "Execution diagnostics"}

        for missing_scope in ("routines:write", "schedules:write", "agents:reader:run"):
            assert (
                client.post(
                    path + "/trigger", headers=headers("alice", [s for s in scopes if s != missing_scope])
                ).status_code
                == 403
            )
        assert "private-claim-alice" in json.dumps(db.get_schedule(routine_id)["payload"])
        # Another member may pause and resume; timing changes keep the saved execution grant.
        for action, enabled in (("pause", False), ("resume", True)):
            response = client.post(path + "/" + action, headers=headers("bob"))
            assert response.status_code == 200, response.text
            assert response.json()["enabled"] is enabled
            assert response.json()["last_run"]["status"] == "success"
            assert response.json()["schedule_type"] == "scheduled"
            assert "_agno_authorization" not in response.text
            assert "private-claim-alice" not in response.text
        assert "private-claim-alice" in json.dumps(db.get_schedule(routine_id)["payload"])
        assert client.post("/company/setup", headers=headers("bob"), json={"name": "Other setup"}).status_code == 409
    db.close()


@pytest.mark.parametrize("isolation", [False, True])
@pytest.mark.parametrize("managed_roles", [False, True])
@pytest.mark.parametrize("owner", [None, "alice"])
def test_members_trigger_routines_as_themselves(tmp_path, monkeypatch, isolation, managed_roles, owner):
    import asyncio

    import jwt

    from agno.company import Routine
    from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER
    from agno.os.authz import Authorization
    from agno.os.authz.native_engine import NativePolicyEngine
    from agno.os.config import AuthorizationConfig
    from agno.run.authorization import AUTHORIZATION_KEY

    secret = "company-routine-member-trigger-secret"
    scopes = ["routines:write", "schedules:write", "agents:reader:run"]
    db = SqliteDb(db_file=str(tmp_path / "member-trigger.db"))
    authorization = Authorization(db=db, verification_keys=[secret], algorithm="HS256", audience="members")
    if managed_roles:
        authorization.define_role("runner", scopes).assign("bob", "runner")

    def headers(granted):
        if managed_roles:
            NativePolicyEngine(db=db).set_role_scopes("runner", [(scope, "allow") for scope in granted])
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {"sub": "bob", "aud": "members", "scopes": ["agent_os:admin"] if managed_roles else granted},
                secret,
                algorithm="HS256",
            )
        }

    os = AgentOS(
        id="members",
        db=db,
        agents=[Agent(id="reader", telemetry=False)],
        company=CompanyConfig(
            products=[
                Product(
                    id="shared",
                    name="Shared",
                    user_id=owner,
                    routines=[
                        Routine(name="review", executor_type="agent", executor_id="reader", instructions="Review")
                    ],
                )
            ]
        ),
        telemetry=False,
        user_isolation=isolation,
        authorization=authorization if managed_roles else True,
        authorization_config=None
        if managed_roles
        else AuthorizationConfig(verification_keys=[secret], algorithm="HS256"),
    )
    executor = ScheduleExecutor(base_url="http://test", internal_service_token="internal")
    background = AsyncMock(return_value={"status": "success", "status_code": 200})
    monkeypatch.setattr(executor, "_background_run", background)
    monkeypatch.setattr(executor, "_get_client", AsyncMock())
    with TestClient(os.get_app()) as client:
        client.app.state.scheduler_executor = executor
        routine_id = db.get_product("shared")["metadata"]["routine_ids"][0]
        saved = db.get_schedule(routine_id)
        # A stored creator grant must never become a manual caller's authority.
        payload = {
            **saved["payload"],
            AUTHORIZATION_KEY: {"context": {"principal_id": owner, "scopes": ["agent_os:admin"]}},
        }
        db.update_schedule(routine_id, payload=payload)
        saved = db.get_schedule(routine_id)
        path = "/company/routines/" + routine_id
        for missing in scopes:
            denied = client.post(path + "/trigger", headers=headers([scope for scope in scopes if scope != missing]))
            assert denied.status_code == 403, denied.text
        background.assert_not_awaited()
        assert db.get_schedule_runs(routine_id)[1] == 0

        auth = headers(scopes)
        response = client.post(path + "/trigger", headers=auth)
        assert response.status_code == 200, response.text
        assert response.json()["user_id"] == "bob"
        assert db.get_schedule_run(response.json()["id"])["user_id"] == "bob"
        forwarded_headers, form = background.call_args.args[2:4]
        assert forwarded_headers[SCHEDULE_OWNER_HEADER] == "bob"
        assert form["user_id"] == "bob"
        snapshot = json.loads(forwarded_headers[AUTHORIZATION_HEADER])
        assert snapshot["context"]["principal_id"] == "bob"
        assert snapshot["company_routine"] is True
        assert snapshot["company_routine_unscoped"] is False
        assert db.get_schedule(routine_id) == saved
        assert db.get_product("shared")["user_id"] == owner

        # Generic schedule routes cannot be used to bypass the Company wrapper.
        assert client.post("/schedules/" + routine_id + "/trigger", headers=auth).status_code in (403, 404, 409)
        # Members manage Routines they did not create; timing changes keep the saved grant.
        assert client.post(path + "/pause", headers=auth).json()["enabled"] is False
        assert client.post(path + "/resume", headers=auth).json()["enabled"] is True
        assert db.get_schedule(routine_id)["payload"] == saved["payload"]
        db.update_schedule(routine_id, enabled=False)
        assert client.post(path + "/trigger", headers=auth).status_code == 409
        assert background.await_count == 1
        # Timer execution still uses the saved owner and grant, not the last manual caller.
        scheduled = asyncio.run(executor.execute(saved, db, release_schedule=False))
        assert scheduled["user_id"] == owner
        forwarded_headers = background.call_args.args[2]
        assert forwarded_headers.get(SCHEDULE_OWNER_HEADER) == owner
        snapshot = json.loads(forwarded_headers[AUTHORIZATION_HEADER])
        assert snapshot["context"]["principal_id"] == owner

        # Automatic acceptance runs on the saved grant, so only its grantor may start it, in both isolation modes.
        metadata = {**saved["payload"]["metadata"], "auto_accept": {"executor_type": "agent", "executor_id": "reader"}}

        def grant(user_id):
            payload = {**saved["payload"], "metadata": metadata, "_agno_company_acceptance": {"user_id": user_id}}
            db.update_schedule(routine_id, enabled=True, payload=payload)

        grant(owner)
        dispatched = background.await_count
        response = client.post(path + "/trigger", headers=auth)
        assert response.status_code == 403, response.text
        assert background.await_count == dispatched
        if owner and not managed_roles:
            token = jwt.encode({"sub": owner, "aud": "members", "scopes": scopes}, secret, algorithm="HS256")
            response = client.post(path + "/trigger", headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200, response.text
            assert response.json()["user_id"] == owner
        if not managed_roles:
            # An admin whose scopes are authoritative keeps the existing bypass.
            token = jwt.encode(
                {"sub": "root", "aud": "members", "scopes": ["agent_os:admin"]}, secret, algorithm="HS256"
            )
            response = client.post(path + "/trigger", headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200, response.text
        # A member who re-authorized acceptance holds the grant, whoever created the Routine.
        grant("bob")
        response = client.post(path + "/trigger", headers=auth)
        assert response.status_code == 200, response.text
        assert response.json()["user_id"] == "bob"
    db.close()


def test_manual_trigger_without_auth_keeps_seeded_owner(tmp_path, monkeypatch):
    from agno.company import Routine
    from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER

    db = SqliteDb(db_file=str(tmp_path / "no-auth-trigger.db"))
    os = AgentOS(
        db=db,
        agents=[Agent(id="reader", telemetry=False)],
        company=CompanyConfig(
            products=[
                Product(
                    id="seeded",
                    name="Seeded",
                    user_id="alice",
                    routines=[
                        Routine(name="review", executor_type="agent", executor_id="reader", instructions="Review")
                    ],
                )
            ]
        ),
        telemetry=False,
    )
    executor = ScheduleExecutor(base_url="http://test", internal_service_token="internal")
    background = AsyncMock(return_value={"status": "success", "status_code": 200})
    monkeypatch.setattr(executor, "_background_run", background)
    monkeypatch.setattr(executor, "_get_client", AsyncMock())
    with TestClient(os.get_app()) as client:
        client.app.state.scheduler_executor = executor
        routine_id = db.get_product("seeded")["metadata"]["routine_ids"][0]
        response = client.post("/company/routines/" + routine_id + "/trigger")
        assert response.status_code == 200, response.text
        # No caller identity: the run stays attributed to the saved owner, as a scheduled run would be.
        assert response.json()["user_id"] == "alice"
        forwarded_headers, form = background.call_args.args[2:4]
        assert forwarded_headers[SCHEDULE_OWNER_HEADER] == "alice"
        assert form["user_id"] == "alice"
    db.close()


def test_members_manage_products_and_routines_they_did_not_create_under_isolation(tmp_path):
    from datetime import datetime, timedelta, timezone

    import jwt

    from agno.os.config import AuthorizationConfig

    secret = "member-routines-isolation-secret"
    scopes = [
        "products:read",
        "products:write",
        "products:delete",
        "routines:read",
        "routines:write",
        "schedules:write",
    ]

    def headers(user):
        claims = {
            "sub": user,
            "aud": "member-routines",
            "scopes": [*scopes, "agents:reader:run"],
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}

    db = SqliteDb(db_file=str(tmp_path / "members.db"))
    os = AgentOS(
        id="member-routines",
        db=db,
        agents=[Agent(id="reader", telemetry=False)],
        company=CompanyConfig(products=[Product(id="declared", name="Declared")]),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[secret], algorithm="HS256", user_isolation=True),
    )
    body = dict(name="intake", template="intake", executor_type="agent", executor_id="reader")
    with TestClient(os.get_app()) as client:
        owned = client.post("/company/products", headers=headers("alice"), json={"name": "Alice's"}).json()
        for product_id in ("declared", owned["id"]):
            created = client.post("/company/routines", headers=headers("bob"), json={**body, "product_id": product_id})
            assert created.status_code == 201, created.text
            routine = created.json()
            assert routine["user_id"] == "bob"
            assert routine["id"] in db.get_product(product_id)["metadata"]["routine_ids"]
            path = "/company/routines/" + routine["id"]
            assert (
                client.patch(path, headers=headers("bob"), json={"instructions": "Report changes"}).status_code == 200
            )
            assert client.post(path + "/pause", headers=headers("bob")).json()["enabled"] is False
            # Other members manage it too, and the creator stays recorded.
            resumed = client.post(path + "/resume", headers=headers("alice"))
            assert resumed.json()["enabled"] is True
            assert resumed.json()["user_id"] == "bob"
            edited = client.patch(path, headers=headers("alice"), json={"instructions": "Alice's review"})
            assert edited.status_code == 200, edited.text
            assert "Alice's review" in edited.json()["payload"]["message"]
            assert edited.json()["user_id"] == "bob"
        # Product writes need the scope, not ownership; the creator stays recorded.
        for product_id in ("declared", owned["id"]):
            renamed = client.patch("/company/products/" + product_id, headers=headers("bob"), json={"name": "x"})
            assert renamed.status_code == 200, renamed.text
        assert db.get_product(owned["id"])["user_id"] == "alice"
        client.delete("/company/products/" + owned["id"], headers=headers("bob")).raise_for_status()
        archived = client.post("/company/routines", headers=headers("bob"), json={**body, "product_id": owned["id"]})
        assert archived.status_code == 404
    db.close()


@pytest.mark.parametrize("failure", ["create_schedule", "add_product_routine"])
def test_setup_retry_repairs_partial_records_and_retains_edits(system, tmp_path, monkeypatch, failure):
    client, os, db = system
    body = dict(
        name="Setup",
        sources=[dict(type="markdown", reference=str(tmp_path / "readme.md"))],
        routines=[
            dict(name="refresh", template="refresh", executor_type="agent", executor_id="reader", cron_expr="0 * * * *")
        ],
    )
    original = getattr(db, failure)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Injected storage failure")

    monkeypatch.setattr(db, failure, unavailable)
    with pytest.raises(RuntimeError, match="Injected storage failure"):
        client.post("/company/setup", json=body)
    monkeypatch.setattr(db, failure, original)
    manager = CompanyManager(db)
    manager.update("company-setup", name="Human edit")
    source = manager.list_sources()[0][0]
    manager.delete_source(source["id"])
    schedules = db.get_schedules()[0]
    if schedules:
        db.update_schedule(
            schedules[0]["id"], enabled=False, payload={**schedules[0]["payload"], "message": "Human instructions"}
        )
    retry = client.post("/company/setup", json=body)
    assert retry.status_code == 200, retry.text
    assert retry.json()["name"] == "Human edit"
    schedules = db.get_schedules()[0]
    assert len(schedules) == 1
    assert retry.json()["metadata"]["routine_ids"] == [schedules[0]["id"]]
    assert manager.list_sources()[1] == 0
    if failure == "add_product_routine":
        assert schedules[0]["enabled"] is False
        assert schedules[0]["payload"]["message"] == "Human instructions"
    client.post("/company/setup", json=body).raise_for_status()
    assert len(db.get_schedules()[0]) == 1
    manager.delete("company-setup")
    assert client.post("/company/setup", json=body).json()["deleted_at"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("async_tools", [False, True])
async def test_source_tools_only_require_source_and_proposal_scopes(tmp_path, async_tools):
    from agno.os.auth import _default_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run import RunContext
    from agno.run.authorization import RunAuthorization
    from agno.tools.company import CompanyTools

    db = SqliteDb(db_file=str(tmp_path / "permissions.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Docs")
    project = manager.create_project(product_id=product["id"], name="Documentation")
    path = tmp_path / "page.md"
    path.write_text("Document the released API")
    source = manager.create_source(product_id=product["id"], type="markdown", reference=str(path))
    tools = CompanyTools(db)
    authority = RunAuthorization(
        _default_authorization_provider(),
        AuthorizationContext(principal_id="reader", scopes=["sources:read", "tasks:write"]),
    )
    context = RunContext(run_id="source-run", session_id="session", user_id="reader")
    args = dict(
        source_id=source["id"],
        project_id=project["id"],
        title="Document API",
        brief="Write API guide",
        proposal_key="api-guide",
        evidence_links=[path.as_uri()],
        _agno_run_context=context,
    )
    with authorization_scope(lambda: _RoutineAuthorization(authority, "routine")):
        if async_tools:
            evidence = [
                json.loads(await tools.aread_product_source(source["id"], path=path.name, _agno_run_context=context))
            ]
            args["evidence_hashes"] = {item["link"]: item["content_hash"] for item in evidence}
            task = json.loads(await tools.aintake_product_source(**args))
        else:
            evidence = [json.loads(tools.read_product_source(source["id"], path=path.name, _agno_run_context=context))]
            args["evidence_hashes"] = {item["link"]: item["content_hash"] for item in evidence}
            task = json.loads(tools.intake_product_source(**args))
    assert evidence[0]["content_hash"] == task["evidence"][0]["content_hash"]
    assert task["status"] == "backlog"
    authority.context.scopes = ["tasks:write"]
    with authorization_scope(lambda: authority):
        with pytest.raises(PermissionError):
            tools.read_product_source(source["id"], _agno_run_context=context)
    db.close()


def test_company_yaml_rejects_unknown_keys():
    from pydantic import ValidationError

    from agno.os.config import AgentOSConfig

    with pytest.raises(ValidationError):
        AgentOSConfig(company={"produts": []})


@pytest.mark.parametrize("template", ["refresh", "intake", "summary"])
def test_each_routine_template_targets_the_product_in_its_message(system, template):
    client, _, _ = system
    product = client.post("/company/products", json={"name": "Target"}).json()
    row = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name=template,
            template=template,
            executor_type="agent",
            executor_id="reader",
            cron_expr="0 * * * *",
        ),
    ).json()
    assert row["payload"]["metadata"]["product_id"] == product["id"]
    assert product["id"] in row["payload"]["message"]
    instructions = load_routine_skills().get_skill(template).instructions
    assert "Product identified in the message" in instructions
    assert "product_id in run metadata" not in instructions


def test_custom_company_tools_resolve_os_interfaces_and_human_origin(tmp_path, monkeypatch):
    from fastapi import APIRouter

    from agno.models.openai import OpenAIResponses
    from agno.os.interfaces.base import BaseInterface
    from agno.run import RunContext
    from agno.tools.company import CompanyTools

    class Interface(BaseInterface):
        type = "slack"

        def get_router(self, **kwargs):
            return APIRouter()

    db = SqliteDb(db_file=str(tmp_path / "summary.db"))
    interface = Interface()
    toolkit = CompanyTools(db)
    executor = Agent(id="custom", tools=[toolkit], telemetry=False)
    os = AgentOS(
        db=db,
        agents=[executor],
        interfaces=[interface],
        company=CompanyConfig(model=OpenAIResponses(id="offline")),
        telemetry=False,
    )
    assert toolkit.interfaces is os.interfaces
    assert "summarize_company_product" not in os.company_manager.tools[0].functions
    delivery = AsyncMock()
    monkeypatch.setattr("agno.company.summary.adeliver_summary", delivery)
    with TestClient(os.get_app()) as client:
        product = client.post(
            "/company/products",
            json={"name": "Summary", "metadata": {"summary": {"interface": "slack", "destination": "configured"}}},
        ).json()
        project = client.post("/company/projects", json={"product_id": product["id"], "name": "Release"}).json()
        task = client.post(
            "/company/tasks", json={"product_id": product["id"], "project_id": project["id"], "title": "Human work"}
        ).json()
        assert task["origin"] == "human" and task["routine_id"] is None and task["dedupe_key"] is None
        context = RunContext(run_id="report", session_id="session", user_id="alice")
        proposed = json.loads(
            toolkit.propose_company_task(
                product["id"], "Proposed work", project_id=project["id"], _agno_run_context=context
            )
        )
        assert proposed["origin"] == "product_manager"
        result = json.loads(
            toolkit.summarize_company_product(
                product["id"], narrative="Two items need review.", _agno_run_context=context
            )
        )
        assert result["delivered"] is True
        page = CompanyManager(db).read_wiki(product["id"], "summary.md").content
        assert "Two items need review." in page and "## What changed" in page
        assert "Two items need review." in delivery.await_args.args[3]
        assert "Company summary snapshot" not in delivery.await_args.args[3]
    db.close()


@pytest.mark.parametrize("name", ["weekday/refresh", "x" * 240])
def test_routine_composed_name_validation_returns_422(system, name):
    client, _, db = system
    product = client.post("/company/products", json={"name": "Docs"}).json()
    body = dict(
        product_id=product["id"],
        name=name,
        template="refresh",
        executor_type="agent",
        executor_id="reader",
        cron_expr="0 * * * *",
    )
    response = client.post("/company/routines", json=body)
    assert response.status_code == 422, response.text
    assert "name" in response.json()["detail"]
    assert not (db.get_product(product["id"]).get("metadata") or {}).get("routine_ids")
    body["name"] = "x" * (255 - len(product["id"]) - 1)
    created = client.post("/company/routines", json=body)
    assert created.status_code == 201, created.text
    assert len(created.json()["name"]) == 255
    assert client.patch("/company/routines/" + created.json()["id"], json={"cron_expr": "x" * 129}).status_code == 422


@pytest.mark.parametrize("name", ["weekday/refresh", "x" * 250])
def test_setup_invalid_composed_name_has_no_partial_writes(system, name):
    client, _, db = system
    response = client.post(
        "/company/setup",
        json={
            "name": "Docs",
            "routines": [
                dict(name=name, template="refresh", executor_type="agent", executor_id="reader", cron_expr="0 * * * *")
            ],
        },
    )
    assert response.status_code == 422, response.text
    assert db.get_products()[1] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("async_tools", [False, True])
@pytest.mark.parametrize("routine_id", [None, "routine"])
async def test_routine_cannot_use_plain_task_proposals(tmp_path, async_tools, routine_id):
    from agno.run import RunContext
    from agno.tools.company import CompanyTools

    db = SqliteDb(db_file=str(tmp_path / "routine-proposals.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Docs")
    project = manager.create_project(product_id=product["id"], name="Documentation")
    tools = CompanyTools(db)
    context = RunContext(run_id="run", session_id="session", authorization=_RoutineAuthorization(None, routine_id))
    for _ in range(3):
        with pytest.raises(PermissionError, match="intake_product_source"):
            if async_tools:
                await tools.apropose_company_task(
                    product["id"], "Repeated", project_id=project["id"], _agno_run_context=context
                )
            else:
                tools.propose_company_task(
                    product["id"], "Repeated", project_id=project["id"], _agno_run_context=context
                )
    assert manager.list_tasks()[1] == 0
    context.authorization = None
    if async_tools:
        result = await tools.apropose_company_task(
            product["id"], "Human-directed", project_id=project["id"], _agno_run_context=context
        )
    else:
        result = tools.propose_company_task(
            product["id"], "Human-directed", project_id=project["id"], _agno_run_context=context
        )
    assert json.loads(result)["origin"] == "product_manager"
    db.close()


def test_bounded_source_reader_preserves_configured_boundaries(tmp_path):
    from agno.company.sources import browse_source, read_source

    root = tmp_path / "repo"
    root.mkdir()
    (root / "allowed.md").write_text("Allowed")
    (root / "other.md").write_text("Not configured")
    (root / ".env").write_text("SECRET")
    outside = tmp_path / "outside.md"
    outside.write_text("Outside")
    (root / "escape.md").symlink_to(outside)
    source = dict(id="s", type="git", reference=str(root), config={"paths": ["allowed.md"]})
    assert browse_source(source, "run")["data"] == [{"path": "allowed.md", "link": (root / "allowed.md").as_uri()}]
    for path in ("other.md", ".env", "../outside.md", "escape.md"):
        with pytest.raises(ValueError):
            browse_source(source, "run", path=path)
        with pytest.raises(ValueError):
            read_source(source, "run", links=[(root / path).as_uri()])
    for options in ({"offset": -1}, {"limit": 0}, {"limit": 101}, {"max_chars": 16001}, {"content_offset": -1}):
        with pytest.raises(ValueError):
            browse_source(source, "run", **options)
    assert browse_source(source, "run", offset=99)["next_offset"] is None
    with pytest.raises(ValueError, match="beyond the document"):
        browse_source(source, "run", path="allowed.md", content_offset=100)


def test_website_source_is_bounded_and_cannot_select_another_url(monkeypatch):
    from agno.company.sources import browse_source, read_source
    from agno.knowledge.document import Document
    from agno.utils.string import hash_string_sha256

    content = "Observed website content " * 3000
    calls = []

    def reader(self, url):
        calls.append(url)
        return [Document(content=content)]

    monkeypatch.setattr("agno.knowledge.reader.website_reader.WebsiteReader.read", reader)
    source = dict(id="s", type="website", reference="https://docs.example.test/page", config={})
    page = browse_source(source, "run")
    assert not calls and page["data"][0]["path"] == source["reference"]
    fragment = browse_source(source, "run", path=source["reference"])
    assert len(fragment["content"]) == 8000 and fragment["next_content_offset"] == 8000
    assert fragment["content_hash"] == hash_string_sha256(content)
    with pytest.raises(ValueError):
        browse_source(source, "run", path="https://unconfigured.test")
    with pytest.raises(ValueError):
        read_source(source, "run", links=["https://unconfigured.test"])
    assert calls == [source["reference"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_tools", [False, True])
async def test_refresh_requires_routine_and_saved_delete_authority(tmp_path, async_tools):
    import asyncio

    from agno.os.auth import _default_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run import RunContext
    from agno.run.authorization import RunAuthorization
    from agno.tools.company import CompanyTools

    db = SqliteDb(db_file=str(tmp_path / "refresh.db"))
    manager = CompanyManager(db)
    product = manager.create(name="Docs", user_id="owner")
    tools = CompanyTools(db, user_isolation=True)
    context = RunContext(run_id="refresh", session_id="session", user_id="owner")

    async def invoke():
        if async_tools:
            return await tools.arefresh_company_product(product["id"], _agno_run_context=context)
        return await asyncio.to_thread(tools.refresh_company_product, product["id"], _agno_run_context=context)

    with pytest.raises(PermissionError, match="Routine authority"):
        await invoke()
    scopes = ["products:read", "projects:read", "tasks:read", "wiki:read", "wiki:write"]
    authority = RunAuthorization(
        _default_authorization_provider(), AuthorizationContext(principal_id="owner", scopes=scopes)
    )
    with authorization_scope(lambda: _RoutineAuthorization(authority, "refresh")):
        with pytest.raises(PermissionError, match="projects:delete"):
            await invoke()
    authority = RunAuthorization(
        _default_authorization_provider(),
        AuthorizationContext(principal_id="owner", scopes=[*scopes, "projects:delete", "tasks:delete"]),
    )
    with authorization_scope(lambda: _RoutineAuthorization(authority, "refresh")):
        assert json.loads(await invoke())["completion_proposals"] == []
    db.close()


@pytest.mark.parametrize("failure", ["link", "enable"])
@pytest.mark.parametrize("pause_pending", [False, True])
def test_routine_create_recovers_disabled_pending_schedule(system, monkeypatch, failure, pause_pending):
    client, _, db = system
    product = client.post("/company/products", json={"name": "Docs"}).json()
    body = dict(
        product_id=product["id"],
        name="refresh",
        template="refresh",
        executor_type="agent",
        executor_id="reader",
        cron_expr="0 * * * *",
    )
    method = "add_product_routine" if failure == "link" else "update_schedule"
    original = getattr(db, method)

    def fail(*args, **kwargs):
        raise RuntimeError("Interrupted creation")

    monkeypatch.setattr(db, method, fail)
    with pytest.raises(RuntimeError, match="Interrupted creation"):
        client.post("/company/routines", json=body)
    rows, total = db.get_schedules()
    assert total == 1
    pending = rows[0]
    assert pending["enabled"] is False and pending["next_run_at"] is None
    assert pending["payload"]["_agno_pending_creation"] is True
    assert db.get_schedules(enabled=True)[1] == 0
    monkeypatch.setattr(db, method, original)
    # A changed request must not repurpose an interrupted creation.
    assert client.post("/company/routines", json={**body, "cron_expr": "30 * * * *"}).status_code == 409
    if pause_pending:
        assert client.post("/company/routines/" + pending["id"] + "/pause").status_code == 200
        assert client.post("/company/routines", json=body).status_code == 409
        assert db.get_schedule(pending["id"])["enabled"] is False
        assert client.post("/company/routines/" + pending["id"] + "/resume").status_code == 200
        assert db.get_product(product["id"])["metadata"]["routine_ids"] == [pending["id"]]
        return
    result = client.post("/company/routines", json=body)
    assert result.status_code == 201, result.text
    assert result.json()["id"] == pending["id"] and result.json()["enabled"] is True
    assert "_agno_pending_creation" not in result.json()["payload"]
    assert db.get_product(product["id"])["metadata"]["routine_ids"] == [pending["id"]]
    assert db.get_schedules()[1] == 1
    # A later duplicate POST must not reactivate a deliberate pause.
    assert client.post("/company/routines/" + pending["id"] + "/pause").status_code == 200
    assert client.post("/company/routines", json=body).status_code == 409
    assert db.get_schedule(pending["id"])["enabled"] is False


@pytest.mark.parametrize("isolation", [False, True])
def test_pending_routine_creation_cannot_be_recovered_by_another_creator(tmp_path, monkeypatch, isolation):
    from datetime import datetime, timedelta, timezone

    import jwt

    from agno.os.config import AuthorizationConfig

    secret = "pending-routine-test-secret"
    db = SqliteDb(db_file=str(tmp_path / "pending.db"))
    os = AgentOS(
        id="pending-routines",
        db=db,
        agents=[Agent(id="reader", telemetry=False)],
        company=CompanyConfig(),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[secret], algorithm="HS256", user_isolation=isolation
        ),
    )

    def headers(user):
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {
                    "sub": user,
                    "aud": "pending-routines",
                    "scopes": ["products:write", "routines:write", "schedules:write", "agents:reader:run"],
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                },
                secret,
                algorithm="HS256",
            )
        }

    original = db.add_product_routine

    def fail(*args, **kwargs):
        raise RuntimeError("Link interrupted")

    with TestClient(os.get_app()) as client:
        product = client.post("/company/products", json={"name": "Docs"}, headers=headers("alice")).json()
        body = dict(
            product_id=product["id"],
            name="refresh",
            template="refresh",
            executor_type="agent",
            executor_id="reader",
            cron_expr="0 * * * *",
        )
        monkeypatch.setattr(db, "add_product_routine", fail)
        with pytest.raises(RuntimeError, match="Link interrupted"):
            client.post("/company/routines", json=body, headers=headers("alice"))
        pending = db.get_schedules()[0][0]
        assert pending["user_id"] == "alice"
        monkeypatch.setattr(db, "add_product_routine", original)
        bob = client.post("/company/routines", json=body, headers=headers("bob"))
        # Scheduler names are per creator: Bob can create his own, but cannot recover Alice's.
        assert bob.status_code == 201, bob.text
        assert bob.json()["id"] != pending["id"] and bob.json()["user_id"] == "bob"
        assert db.get_schedule(pending["id"])["enabled"] is False
        alice = client.post("/company/routines", json=body, headers=headers("alice"))
        assert alice.status_code == 201, alice.text
        assert alice.json()["id"] == pending["id"] and alice.json()["enabled"] is True
    db.close()


@pytest.mark.parametrize("instructions", [None, "", "  "])
def test_custom_routine_requires_instructions(system, instructions):
    client, _, _ = system
    product = client.post("/company/products", json={"name": "Custom"}).json()
    response = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="custom",
            executor_type="agent",
            executor_id="reader",
            cron_expr="0 * * * *",
            instructions=instructions,
        ),
    )
    assert response.status_code == 422, response.text


def test_custom_routine_edits_and_frozen_template(system, monkeypatch):
    client, _, db = system
    product = client.post("/company/products", json={"name": "Custom"}).json()
    response = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="custom",
            executor_type="agent",
            executor_id="reader",
            cron_expr="0 * * * *",
            instructions="Check quietly",
        ),
    )
    assert response.status_code == 201, response.text
    routine = response.json()
    assert routine["payload"]["metadata"]["template"] is None
    path = "/company/routines/" + routine["id"]
    changed = client.patch(path, json={"name": "renamed", "instructions": "New instructions", "cron_expr": "0 9 * * *"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == product["id"] + ".renamed"
    assert changed.json()["payload"]["message"].endswith("New instructions")
    assert client.patch(path, json={"instructions": " "}).status_code == 422
    assert client.patch(path, json={"name": "!"}).status_code == 422
    assert client.patch(path, json={"name": ""}).status_code == 422
    assert client.patch(path, json={"executor_id": "missing"}).status_code == 422
    assert db.get_schedule(routine["id"])["payload"]["metadata"]["auto_accept"] is False
    templated = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="template",
            template="summary",
            executor_type="agent",
            executor_id="reader",
            cron_expr="0 * * * *",
        ),
    ).json()
    monkeypatch.setattr(
        "agno.company.routines.load_routine_skills", lambda: pytest.fail("Existing instructions must not reload Skills")
    )
    edited = client.patch("/company/routines/" + templated["id"], json={"name": "saved-template"})
    assert edited.status_code == 200
    assert edited.json()["payload"]["message"] == templated["payload"]["message"]
    edited = client.patch("/company/routines/" + templated["id"], json={"instructions": "Human-edited summary"})
    assert edited.status_code == 200
    assert edited.json()["payload"]["metadata"] == templated["payload"]["metadata"]
    assert "instructions" not in edited.json()["payload"]["metadata"]


def test_isolated_company_reads_require_subject_and_executor_edits_require_run_scope(tmp_path):
    import jwt

    from agno.os.config import AuthorizationConfig

    secret = "company-contract-secret"
    db = SqliteDb(db_file=str(tmp_path / "identity.db"))
    os = AgentOS(
        id="contract",
        db=db,
        agents=[Agent(id="reader", telemetry=False), Agent(id="other", telemetry=False)],
        company=CompanyConfig(),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[secret], algorithm="HS256", user_isolation=True),
    )
    scopes = [
        "products:read",
        "products:write",
        "projects:read",
        "tasks:read",
        "sources:read",
        "routines:read",
        "routines:write",
        "schedules:write",
        "schedules:read",
        "agents:reader:run",
        "wiki:read",
    ]

    def headers(subject):
        claims = {"aud": "contract", "scopes": scopes}
        if subject:
            claims["sub"] = subject
        return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}

    with TestClient(os.get_app()) as client:
        product = client.post("/company/products", json={"name": "Identity"}, headers=headers("owner")).json()
        routine = client.post(
            "/company/routines",
            json=dict(
                product_id=product["id"],
                name="custom",
                instructions="Quiet",
                executor_type="agent",
                executor_id="reader",
                cron_expr="0 * * * *",
            ),
            headers=headers("owner"),
        )
        assert routine.status_code == 201, routine.text
        path = "/company/routines/" + routine.json()["id"]
        for route in [
            "/company/products",
            "/company/products/" + product["id"],
            "/company/projects",
            "/company/tasks",
            "/company/sources",
            "/company/routines",
            path + "/runs",
            "/company/attention",
        ]:
            result = client.get(route, headers=headers(None))
            assert result.status_code == 403, (route, result.text)
        refused = client.patch(path, json={"executor_id": "other"}, headers=headers("owner"))
        assert refused.status_code == 403, refused.text
        assert db.get_schedule(routine.json()["id"])["target_id"] == "reader"
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_tools", [False, True])
async def test_source_tool_requires_write_scope_and_hides_injected_identity(tmp_path, async_tools):
    from types import SimpleNamespace

    from agno.os.auth import _default_authorization_provider
    from agno.os.authz.provider import AuthorizationContext
    from agno.run.authorization import RunAuthorization
    from agno.run.base import RunContext
    from agno.tools.company import CompanyTools

    db = SqliteDb(db_file=str(tmp_path / "scoped-source.db"))
    product = CompanyManager(db).create(name="Owned", user_id="owner")
    toolkit = CompanyTools(db, user_isolation=True)
    authority = RunAuthorization(
        _default_authorization_provider(), AuthorizationContext(principal_id="owner", scopes=["sources:read"])
    )
    context = RunContext(run_id="run", session_id="session", authorization=authority)
    fn = toolkit.aadd_product_source if async_tools else toolkit.add_product_source
    arguments = dict(
        product_id=product["id"],
        reference="https://example.test/page",
        _agno_run_context=context,
        _agno_agent=SimpleNamespace(id="finder"),
    )
    with pytest.raises(PermissionError):
        if async_tools:
            await fn(**arguments)
        else:
            fn(**arguments)
    authority.context.scopes = ["sources:write"]
    result = json.loads(await fn(**arguments) if async_tools else fn(**arguments))
    assert result["config"]["metadata"] == {"agent_id": "finder", "run_id": "run"}
    function = (toolkit.get_async_functions() if async_tools else toolkit.functions)["add_product_source"]
    function.process_entrypoint()
    assert not any(key.startswith("_agno") for key in function.parameters["properties"])
    assert "type" not in function.parameters["properties"]
    db.close()


@pytest.mark.parametrize("task_status", ["backlog", "ready", "in_progress", "in_review", "done", "cancelled"])
@pytest.mark.parametrize("run_status", ["ERROR", "CANCELLED", "FAILED", "error", "COMPLETED"])
def test_summary_failure_predicate_matches_attention(task_status, run_status):
    from agno.company.summary import _summary_report

    report = _summary_report(
        {"name": "Product"},
        {},
        [
            {
                "id": "task",
                "title": "Work",
                "status": task_status,
                "result": {"status": run_status, "error": "Execution detail"},
            }
        ],
        "Observed state",
        "",
    )
    unresolved = task_status == "in_progress" and run_status in {"ERROR", "CANCELLED"}
    assert ("No failed Tasks." not in report) == unresolved


@pytest.mark.parametrize("isolation", [False, True])
def test_executor_edit_reauthorizes_existing_policy_and_restamps_grant(tmp_path, isolation):
    import jwt

    from agno.os.config import AuthorizationConfig

    secret = "company-policy-executor-edit-secret"
    db = SqliteDb(db_file=str(tmp_path / "policy-edit.db"))
    os = AgentOS(
        id="policy-edit",
        db=db,
        agents=[Agent(id="reader", db=db, telemetry=False), Agent(id="other", db=db, telemetry=False)],
        company=CompanyConfig(),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[secret], algorithm="HS256", user_isolation=isolation
        ),
    )

    def headers(scopes):
        return {
            "Authorization": "Bearer "
            + jwt.encode({"sub": "owner", "aud": "policy-edit", "scopes": scopes}, secret, algorithm="HS256")
        }

    admin = headers(["agent_os:admin"])
    with TestClient(os.get_app()) as client:
        product = client.post("/company/products", json={"name": "Policy"}, headers=admin).json()
        created = client.post(
            "/company/routines",
            json=dict(
                product_id=product["id"],
                name="custom",
                instructions="Inspect",
                executor_type="agent",
                executor_id="reader",
                cron_expr="0 * * * *",
                auto_accept=dict(executor_type="agent", executor_id="reader", limits={"expires_at": 4102444800}),
            ),
            headers=admin,
        )
        assert created.status_code == 201, created.text
        routine_id = created.json()["id"]
        before = db.get_schedule(routine_id)
        scopes = ["products:read", "routines:write", "schedules:write", "tasks:write", "wiki:read", "agents:other:run"]
        denied = client.patch("/company/routines/" + routine_id, json={"executor_id": "other"}, headers=headers(scopes))
        assert denied.status_code == 403, denied.text
        assert db.get_schedule(routine_id) == before
        generic = client.patch(
            "/schedules/" + routine_id, json={"endpoint": "/agents/other/runs"}, headers=headers(scopes)
        )
        assert generic.status_code == 409, generic.text
        assert db.get_schedule(routine_id) == before
        scopes.append("agents:reader:run")
        changed = client.patch(
            "/company/routines/" + routine_id, json={"executor_id": "other"}, headers=headers(scopes)
        )
        assert changed.status_code == 200, changed.text
        after = db.get_schedule(routine_id)
        assert after["target_id"] == "other"
        assert after["payload"]["metadata"]["auto_accept"] == before["payload"]["metadata"]["auto_accept"]
        assert after["payload"]["_agno_company_acceptance"] != before["payload"]["_agno_company_acceptance"]


def test_managed_schedule_mutations_use_company_routes(system):
    client, os, db = system
    product = client.post("/company/products", json={"name": "SDK"}).json()
    created = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="check",
            instructions="Check",
            executor_type="agent",
            executor_id="reader",
            cron_expr="0 * * * *",
        ),
    )
    assert created.status_code == 201
    identifier = created.json()["id"]
    assert client.patch("/schedules/" + identifier, json={"payload": {"message": "Break metadata"}}).status_code == 409
    assert client.delete("/schedules/" + identifier).status_code == 409
    assert client.post("/schedules/" + identifier + "/enable").status_code == 409
    assert client.delete("/company/products/" + product["id"]).status_code == 204
    assert client.post("/company/routines/" + identifier + "/pause").status_code == 200
    assert client.post("/company/routines/" + identifier + "/resume").status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("automation", [False, True])
async def test_archived_product_prevents_executor_dispatch(tmp_path, monkeypatch, automation):
    from types import SimpleNamespace

    from agno.company.routines import _CompanyScheduleExecutor
    from agno.company.scheduler import CompanyScheduleExecutor
    from agno.scheduler import ScheduleManager

    db = SqliteDb(db_file=str(tmp_path / "archive-dispatch.db"))
    manager = CompanyManager(db)
    product = manager.create(name="SDK")
    schedule = ScheduleManager(db).create(
        name="check",
        cron="0 * * * *",
        endpoint="/agents/reader/runs",
        payload={"message": "check", "metadata": {"product_id": product["id"]}},
        provenance={"managed_by": "company", "target_type": "agent", "target_id": "reader"},
    )
    manager.delete(product["id"])
    dispatch = AsyncMock()
    monkeypatch.setattr(ScheduleExecutor, "_call_endpoint", dispatch)
    options = dict(company_db=db, schedule_db=db, base_url="http://test", internal_service_token="internal")
    executor = (
        _CompanyScheduleExecutor(SimpleNamespace(_company_db=db, db=db), None, **options)
        if automation
        else CompanyScheduleExecutor(**options)
    )
    result = await executor.execute(schedule, db)
    assert result["status"] == "failed" and "archived" in result["error"]
    dispatch.assert_not_awaited()
    assert db.get_schedule(schedule.id)["enabled"] is False
    assert db.get_schedule(schedule.id)["disabled_reason"] == "company_product_archived"
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_tools", [False, True])
async def test_team_source_uses_injected_team_identity(tmp_path, async_tools):
    from types import SimpleNamespace

    from agno.run.base import RunContext
    from agno.tools.company import CompanyTools

    db = SqliteDb(db_file=str(tmp_path / "team.db"))
    product = CompanyManager(db).create(name="SDK")
    toolkit = CompanyTools(db)
    fn = toolkit.aadd_product_source if async_tools else toolkit.add_product_source
    kwargs = dict(
        product_id=product["id"],
        reference="https://example.com",
        _agno_team=SimpleNamespace(id="team-finder"),
        _agno_run_context=RunContext(run_id="team-run", session_id="session"),
    )
    first = json.loads(await fn(**kwargs) if async_tools else fn(**kwargs))
    again = json.loads(await fn(**kwargs) if async_tools else fn(**kwargs))
    assert again["id"] == first["id"]
    assert first["config"]["metadata"] == {"team_id": "team-finder", "run_id": "team-run"}
    db.close()


def test_internal_scheduler_owner_is_provisioned_without_company(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from agno.os.middleware.user_scope import sync_directory_from_request

    provision = Mock()
    monkeypatch.setattr("agno.os.auth.provision_user_with_default_role", provision)
    store = object()
    request = SimpleNamespace(
        state=SimpleNamespace(authenticated=True, is_internal_service=True),
        app=SimpleNamespace(state=SimpleNamespace(user_store=store, user_auto_provision=True)),
    )
    sync_directory_from_request(request, "schedule-owner")
    assert provision.call_args.args[2] == "schedule-owner"
    request.state.is_internal_service = False
    sync_directory_from_request(request, "jwt-user")
    assert provision.call_count == 1


def test_yaml_products_with_runtime_config_are_not_silently_discarded(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "yaml-runtime.db"))
    config = tmp_path / "config.yaml"
    config.write_text("company:\n  products:\n    - name: YAML product\n")
    os = AgentOS(db=db, config=str(config), company=CompanyConfig(db=db), telemetry=False)
    assert os.company.db is db and os.company.products[0].name == "YAML product"
    with pytest.raises(ValueError, match="not both"):
        AgentOS(
            db=db, config=str(config), company=CompanyConfig(products=[Product(name="Code product")]), telemetry=False
        )
    db.close()
