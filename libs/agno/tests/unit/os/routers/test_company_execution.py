"""Execution gates, shared reads and existing run ownership rules."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company import CompanyManager
from agno.company.execution import _ExecutorAuthorization
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.os.job_queue import QueueWorker
from agno.registry import Registry
from agno.tools.scheduler import SchedulerTools

SECRET = "company-execution-tests-secret-at-least-32-bytes"
SCOPES = [
    "products:read",
    "products:write",
    "tasks:read",
    "tasks:write",
    "wiki:read",
    "agents:writer:run",
]


def headers(user="alice", scopes=None):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": user,
                "aud": "company-execution",
                "scopes": SCOPES if scopes is None else scopes,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            SECRET,
            algorithm="HS256",
        )
    }


@pytest.fixture(params=[False, True], ids=["shared", "isolated"])
def system(request, tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    writer = Agent(id="writer", db=db)
    os = AgentOS(
        id="company-execution",
        db=db,
        registry=Registry(agents=[writer]),
        company=CompanyConfig(),
        telemetry=False,
        user_isolation=request.param,
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256"),
    )
    app = os.get_app()
    config = QueueConfig(durable=True)
    queue = QueueWorker(InMemoryQueueStore(), lambda *a, **k: writer, config, authorization_app=app)
    queue._company_db = db
    app.state.queue_worker = queue
    yield TestClient(app), db, os, queue
    db.close()


def accepted(client):
    product = client.post("/company/products", json={"name": "SDK"}, headers=headers()).json()
    project = client.post(
        "/company/projects",
        json={"product_id": product["id"], "name": "Release"},
        headers=headers(scopes=["projects:write"]),
    ).json()
    task = client.post(
        "/company/tasks",
        json={"product_id": product["id"], "project_id": project["id"], "title": "Draft", "brief": "Write"},
        headers=headers(),
    ).json()
    path = f"/company/tasks/{task['id']}"
    response = client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    return path, response.json()


def test_missing_executor_at_acceptance_and_registry_only_mount(system):
    client, db, os, queue = system
    path, task = accepted(client)
    assert client.post(path + "/runs", headers=headers()).status_code == 202
    other = client.post(
        "/company/tasks",
        json={"product_id": task["product_id"], "project_id": task["project_id"], "title": "Other"},
        headers=headers(),
    ).json()
    denied = client.post(
        f"/company/tasks/{other['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "missing"},
        headers=headers(scopes=["agent_os:admin"]),
    )
    assert denied.status_code == 409
    assert client.get(f"/company/tasks/{other['id']}", headers=headers()).json()["status"] == "backlog"


@pytest.mark.parametrize("revision", [False, True])
def test_start_requires_current_run_and_wiki_permissions(system, revision):
    client, db, os, queue = system
    path, task = accepted(client)
    if revision:
        started = client.post(path + "/runs", headers=headers())
        assert started.status_code == 202, started.text

        async def finish():
            job = await queue.store.claim_job(queue.worker_id, queue.config.lock_grace_seconds)
            assert job["id"] == started.json()["run_id"]
            assert await queue.store.complete_job(job["id"], queue.worker_id, job["attempt"], "completed")

        asyncio.run(finish())
        db.complete_task_run(task["id"], started.json()["run_id"], {"status": "COMPLETED", "content": "Draft"})
    before = db.get_task(task["id"])
    body = {"attempt": 2 if revision else 1}
    for omitted in ("agents:writer:run", "wiki:read", "tasks:write"):
        response = client.post(
            path + "/runs", json=body, headers=headers(scopes=[scope for scope in SCOPES if scope != omitted])
        )
        assert response.status_code == 403, response.text
        assert db.get_task(task["id"]) == before
    assert before["status"] == ("in_review" if revision else "ready")
    os.registry.agents.clear()
    assert client.post(path + "/runs", json=body, headers=headers()).status_code == 409


def test_attention_history_and_duplicates_are_shared(system):
    client, db, os, queue = system
    path, task = accepted(client)
    start = client.post(path + "/runs", headers=headers())
    assert start.status_code == 202, start.text
    duplicate = client.post(path + "/runs", headers=headers("bob"))
    assert duplicate.status_code == 202 and duplicate.json()["run_id"] == start.json()["run_id"]
    assert client.get(path + "/runs", headers=headers("bob")).json()["meta"]["total_count"] == 1
    assert client.get("/company/attention", headers=headers("bob")).status_code == 200
    assert client.get("/company/attention", headers=headers(scopes=[])).status_code == 403
    cancelled = client.post(f"/company/runs/{start.json()['run_id']}/cancel", headers=headers())
    assert cancelled.status_code == 200, cancelled.text


def test_unaccepted_no_queue_and_request_overrides(system):
    client, db, os, queue = system
    path, task = accepted(client)
    assert (
        client.post(path + "/runs", json={"message": "smuggle", "session_id": "foreign"}, headers=headers()).status_code
        == 422
    )
    client.app.state.queue_worker = None
    assert client.post(path + "/runs", headers=headers()).status_code == 503
    assert client.get(path, headers=headers()).json()["status"] == "ready"


def test_python_acceptance_also_validates_registry(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "registry.db"))
    manager = CompanyManager(db)
    product = manager.create(name="SDK")
    project = manager.create_project(product_id=product["id"], name="Release")
    task = manager.create_task(product_id=product["id"], title="Draft", project_id=project["id"])
    with pytest.raises(ValueError, match="missing"):
        manager.transition_task(
            task_id=task["id"], target="ready", reason="Accept", executor_type="agent", executor_id="writer"
        )
    manager.registry = Registry(agents=[Agent(id="writer", tools=[SchedulerTools(db=db)])])
    with pytest.raises(ValueError, match="SchedulerTools"):
        manager.transition_task(
            task_id=task["id"], target="ready", reason="Accept", executor_type="agent", executor_id="writer"
        )
    db.close()


def test_company_executor_cannot_acquire_schedule_mutation_authority():
    authority = _ExecutorAuthorization(None)
    for action in ("write", "delete"):
        with pytest.raises(PermissionError, match="schedules"):
            authority.require("schedules", action)
        with pytest.raises(PermissionError, match="schedules"):
            asyncio.run(authority.arequire("schedules", action))
    authority.require("schedules", "read")


def test_run_routes_without_company_database():
    app = AgentOS(company=CompanyConfig(), telemetry=False).get_app()
    with TestClient(app) as client:
        assert client.get("/company/runs/missing").status_code == 503
        assert client.post("/company/runs/missing/cancel").status_code == 503


def test_missing_product_context_does_not_reserve_execution(system, monkeypatch):
    client, db, os, queue = system
    path, task = accepted(client)
    with pytest.raises(ValueError) as error:
        db.delete_product(task["product_id"])
    assert error.value.args[0]["tasks"] == [{"id": task["id"], "title": task["title"]}]
    # Missing legacy context must still refuse execution, even though archive now refuses active work.
    monkeypatch.setattr(db, "get_product", lambda *args, **kwargs: None)
    response = client.post(path + "/runs", headers=headers())
    assert response.status_code == 404, response.text
    assert db.get_task(task["id"])["job_id"] is None


@pytest.mark.parametrize(
    "resource,executor_id",
    [
        ("agents", "company-manager-internal"),
        ("agents", "product-manager-internal"),
        ("teams", "os-manager-internal"),
        ("agents", "platform-builder-internal"),
        ("agents", "platform-manager-internal"),
    ],
)
def test_registry_mount_excludes_all_framework_executors(resource, executor_id):
    from types import SimpleNamespace

    from agno.company.execution import _mount_executors

    ordinary = SimpleNamespace(id="ordinary")
    reserved = SimpleNamespace(id=executor_id)
    registry = SimpleNamespace(agents=[], teams=[], workflows=[])
    setattr(registry, resource, [ordinary, reserved])
    os = SimpleNamespace(registry=registry, agents=[], teams=[], workflows=[])
    _mount_executors(os)
    assert getattr(os, resource) == [ordinary]


def test_simultaneous_collaborators_share_committed_run(system, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    client, db, os, queue = system
    path, value = accepted(client)
    enqueue = queue.store.enqueue_job

    async def concurrent_starts():
        arrivals = 0
        both_arrived = asyncio.Event()

        async def simultaneous_enqueue(*args, **kwargs):
            nonlocal arrivals
            arrivals += 1
            if arrivals == 2:
                both_arrived.set()
            await asyncio.wait_for(both_arrived.wait(), timeout=10)
            return await enqueue(*args, **kwargs)

        monkeypatch.setattr(queue.store, "enqueue_job", simultaneous_enqueue)
        async with AsyncClient(transport=ASGITransport(app=client.app), base_url="http://test") as async_client:
            return await asyncio.gather(
                async_client.post(path + "/runs", headers=headers("alice")),
                async_client.post(path + "/runs", headers=headers("bob")),
            )

    responses = asyncio.run(concurrent_starts())
    assert all(response.status_code == 202 for response in responses), [response.text for response in responses]
    assert responses[0].json()["run_id"] == responses[1].json()["run_id"]
    saved = db.get_task(value["id"])
    assert saved["status"] == "in_progress"
    assert len([entry for entry in saved["transitions"] if entry.get("attempt") == 1]) == 1


@pytest.mark.asyncio
async def test_automatic_pickup_keeps_accepting_identity_and_run_scope(system):
    from agno.company.routines import _CompanyScheduleExecutor
    from agno.run.authorization import AUTHORIZATION_KEY

    client, db, os, queue = system
    path, task = accepted(client)
    client.app.state.internal_service_token = "company-internal"
    executor = _CompanyScheduleExecutor(
        os, client.app, base_url="http://test", internal_service_token="company-internal"
    )
    # The internal token alone cannot acquire the in-process tick capability.
    response = client.post(path + "/runs", headers={"Authorization": "Bearer company-internal"})
    assert response.status_code == 403, response.text
    stored = db.get_task(task["id"])
    snapshot = stored["transitions"][-1][AUTHORIZATION_KEY]
    assert snapshot["context"]["principal_id"] == "alice"
    assert AUTHORIZATION_KEY not in str(client.get(path, headers=headers()).json())
    result = await executor._dispatch(stored)
    job = await queue.store.get_job(result["run_id"])
    assert job["user_id"] == "alice", job
    assert "schedules:write" not in str(job["payload"].get(AUTHORIZATION_KEY))
    context = json.loads(job["payload"]["input"])["execution_context"]
    assert context["stage"] == "accepted_task_execution"
    assert context["task_id"] == task["id"]
    # A different executor cannot reuse the caller's accepted run grant.
    with pytest.raises(PermissionError):
        from agno.os.authz.run_context import restore_authorization

        await restore_authorization(client.app, snapshot).arequire("agents", "run", "another-agent")


def test_auto_accept_human_scope_and_executor_fence(system):
    client, db, os, queue = system
    scopes = SCOPES + ["routines:write", "routines:read", "schedules:write", "schedules:read"]
    product = client.post("/company/products", json={"name": "Docs"}, headers=headers()).json()
    body = {
        "product_id": product["id"],
        "name": "intake",
        "template": "intake",
        "executor_type": "agent",
        "executor_id": "writer",
        "cron_expr": "0 * * * *",
        "auto_accept": {
            "executor_type": "agent",
            "executor_id": "writer",
            "required_checks": ["executor_registered"],
            "limits": {"expires_at": 4102444800},
        },
    }
    for missing in ("schedules:write", "tasks:write", "agents:writer:run"):
        response = client.post(
            "/company/routines", json=body, headers=headers(scopes=[scope for scope in scopes if scope != missing])
        )
        assert response.status_code == 403, response.text
    response = client.post("/company/routines", json=body, headers=headers(scopes=scopes))
    assert response.status_code == 201, response.text
    routine = response.json()
    assert "_agno_company_acceptance" not in str(routine)
    assert db.get_schedule(routine["id"])["payload"]["_agno_company_acceptance"]["user_id"] == "alice"
    body["name"] = "unknown-check"
    body["auto_accept"]["required_checks"] = ["unknown"]
    assert client.post("/company/routines", json=body, headers=headers(scopes=scopes)).status_code == 422
    # The generic schedule surface cannot mutate a Company Routine. The Company
    # surface validates the executor before stamping the human's authority.
    raw = db.get_schedule(routine["id"])["payload"]
    raw["metadata"]["auto_accept"]["executor_id"] = "another-agent"
    assert (
        client.patch(f"/schedules/{routine['id']}", json={"payload": raw}, headers=headers(scopes=scopes)).status_code
        == 409
    )
    assert (
        client.patch(
            f"/company/routines/{routine['id']}",
            json={"auto_accept": raw["metadata"]["auto_accept"]},
            headers=headers(scopes=scopes),
        ).status_code
        == 422
    )
    # Once registered, the target still requires the editor's own run grant.
    os.registry.agents.append(Agent(id="another-agent", db=db))
    assert (
        client.patch(f"/schedules/{routine['id']}", json={"payload": raw}, headers=headers(scopes=scopes)).status_code
        == 409
    )
    assert (
        client.patch(
            f"/company/routines/{routine['id']}",
            json={"auto_accept": raw["metadata"]["auto_accept"]},
            headers=headers(scopes=scopes),
        ).status_code
        == 403
    )


@pytest.mark.asyncio
async def test_routine_payload_cannot_grant_or_widen_authorization(system, monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from agno.company.routines import _stamp_auto_accept
    from agno.db.schemas.scheduler import Schedule
    from agno.os.authz.run_context import restore_authorization
    from agno.run.authorization import AUTHORIZATION_HEADER, AUTHORIZATION_KEY, authorization_scope
    from agno.scheduler import ScheduleExecutor

    client, db, os, queue = system
    _, task = accepted(client)
    human = db.get_task(task["id"])["transitions"][-1][AUTHORIZATION_KEY]
    captured = {}

    async def capture(_client, _url, headers, payload, *args):
        captured.update(headers=headers, payload=payload)
        return {"status": "success"}

    executor = ScheduleExecutor(base_url="http://test", internal_service_token="internal")
    monkeypatch.setattr(executor, "_get_client", AsyncMock())
    monkeypatch.setattr(executor, "_background_run", capture)
    await executor._call_endpoint(
        Schedule(
            id="routine",
            name="intake",
            cron_expr="* * * * *",
            endpoint="/agents/writer/runs",
            managed_by="company",
            payload={
                AUTHORIZATION_KEY: human,
                "_agno_company_acceptance": {"user_id": "admin"},
                "metadata": {
                    "auto_accept": {"executor_id": "another-agent"},
                    AUTHORIZATION_KEY: {"context": {"scopes": ["agent_os:admin"]}},
                    "company_routine_unscoped": True,
                },
            },
        )
    )
    assert "_agno_company_acceptance" not in captured["payload"]
    authority = restore_authorization(client.app, json.loads(captured["headers"][AUTHORIZATION_HEADER]))
    await authority.arequire("agents", "run", "writer")
    with pytest.raises(PermissionError):
        await authority.arequire("agents", "run", "another-agent")
    with pytest.raises(PermissionError, match="schedules"):
        await authority.arequire("schedules", "write")
    request = SimpleNamespace(state=SimpleNamespace(is_internal_service=False))
    with authorization_scope(lambda: authority):
        with pytest.raises(HTTPException) as error:
            await _stamp_auto_accept(
                request, {"metadata": {"auto_accept": {"executor_type": "agent", "executor_id": "writer"}}}
            )
        assert error.value.status_code == 403
        with pytest.raises(PermissionError, match="cannot accept"):
            CompanyManager(db, os.registry).transition_task(
                task_id=task["id"], target="ready", reason="self-accept", executor_type="agent", executor_id="writer"
            )


@pytest.fixture(params=[False, True], ids=["shared", "isolated"])
def managed_system(request, tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "managed-company.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256")
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("runner", [*SCOPES, "projects:write"])
    authz.define_role("viewer", [scope for scope in SCOPES if scope != "agents:writer:run"])
    authz.seed(admin="root")
    authz.assign("alice", "runner")
    writer = Agent(id="writer", db=db)
    os = AgentOS(
        id="company-execution",
        db=db,
        registry=Registry(agents=[writer]),
        company=CompanyConfig(),
        telemetry=False,
        user_isolation=request.param,
        authorization=authz,
    )
    app = os.get_app()
    queue = QueueWorker(InMemoryQueueStore(), lambda *a, **k: writer, QueueConfig(durable=True), authorization_app=app)
    queue._company_db = db
    app.state.queue_worker = queue
    app.state.internal_service_token = "company-internal"
    yield TestClient(app), db, os, queue, authz
    db.close()


@pytest.mark.asyncio
async def test_automatic_pickup_uses_managed_accepting_identity(managed_system):
    from agno.company.routines import _CompanyScheduleExecutor
    from agno.os.auth import INTERNAL_SCHEDULER_USER_ID
    from agno.os.authz.provider import AuthorizationContext

    client, db, os, queue, authz = managed_system
    path, task = accepted(client)
    executor = _CompanyScheduleExecutor(
        os, client.app, base_url="http://test", internal_service_token="company-internal"
    )
    # The transport principal deliberately has no managed role or run grant.
    assert not await authz.provider.acheck(
        AuthorizationContext(
            principal_id=INTERNAL_SCHEDULER_USER_ID, resource_type="agents", resource_id="writer", action="run"
        )
    )
    result = await executor._dispatch(db.get_task(task["id"]))
    job = await queue.store.get_job(result["run_id"])
    assert job["user_id"] == "alice"
    assert client.get(path, headers=headers()).json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_automatic_pickup_rechecks_managed_grant_at_task_route(managed_system, monkeypatch):
    from agno.company.routines import _CompanyScheduleExecutor
    from agno.os.authz import run_context

    client, db, os, queue, authz = managed_system
    path, task = accepted(client)
    executor = _CompanyScheduleExecutor(
        os, client.app, base_url="http://test", internal_service_token="company-internal"
    )
    original = run_context.request_authorization
    revoked = []

    def revoke_after_transport_checks(request):
        authority = original(request)
        # The middleware has already admitted the Task route. Revoke the target
        # grant when the run route re-reads authority, before it reserves work.
        if request.scope.get("endpoint") is not None:
            authz.set_role("alice", "viewer")
            revoked.append(True)
        return authority

    monkeypatch.setattr(run_context, "request_authorization", revoke_after_transport_checks)
    with pytest.raises(HTTPException, match="Permission required: agents:writer:run") as denied:
        await executor._dispatch(db.get_task(task["id"]))
    assert denied.value.status_code == 403
    assert revoked
    assert db.get_task(task["id"])["status"] == "ready"
    assert db.get_task(task["id"])["job_id"] is None


@pytest.mark.asyncio
async def test_policy_defaults_expiry_and_content_fingerprint(system):
    import copy

    from agno.company.routines import _check_automatic_policy, _policy_fingerprint

    client, db, os, queue = system
    scopes = SCOPES + ["routines:write", "routines:read", "schedules:write", "schedules:read"]
    product = client.post("/company/products", json={"name": "Docs"}, headers=headers()).json()
    policy = {"executor_type": "agent", "executor_id": "writer", "limits": {"expires_at": 4102444800}}
    body = dict(
        product_id=product["id"],
        name="intake",
        template="intake",
        executor_type="agent",
        executor_id="writer",
        cron_expr="0 * * * *",
        auto_accept=policy,
    )
    response = client.post("/company/routines", json=body, headers=headers(scopes=scopes))
    assert response.status_code == 201, response.text
    routine = response.json()
    path = "/company/routines/" + routine["id"]
    raw = db.get_schedule(routine["id"])
    stored = raw["payload"]["metadata"]["auto_accept"]
    assert stored["required_checks"] == ["executor_registered"]
    assert stored["limits"]["max_acceptances"] == 1
    before = _policy_fingerprint(raw)
    import hashlib
    import json

    legacy_content = {key: value for key, value in stored.items() if key != "complete_projects"}
    assert (
        before == hashlib.sha256(json.dumps(legacy_content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )
    receipt = {
        "product_id": product["id"],
        "transitions": [{"target": "ready", "auto_accept": {"routine_id": routine["id"], "policy": before}}],
    }
    fresh = {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": "alice", "aud": "company-execution", "scopes": scopes, "exp": 4102444800}, SECRET, algorithm="HS256"
        )
    }
    for patch in ({"instructions": "Fresh instructions"}, {"auto_accept": policy}):
        response = client.patch(path, json=patch, headers=fresh)
        assert response.status_code == 200, response.text
        assert _policy_fingerprint(db.get_schedule(routine["id"])) == before
        await _check_automatic_policy(db, receipt)
    assert (
        db.get_schedule(routine["id"])["payload"]["_agno_company_acceptance"]
        != raw["payload"]["_agno_company_acceptance"]
    )
    for invalid in (
        {"executor_type": "agent", "executor_id": "writer"},
        {**policy, "limits": {"max_acceptances": 2}},
        {**policy, "required_checks": []},
    ):
        assert client.patch(path, json={"auto_accept": invalid}, headers=fresh).status_code == 422
        payload = copy.deepcopy(raw["payload"])
        payload["metadata"]["auto_accept"] = invalid
        assert client.patch("/schedules/" + routine["id"], json={"payload": payload}, headers=fresh).status_code == 409
    for key, value in (
        ("executor_id", "different"),
        ("complete_projects", True),
        ("source_ids", ["source"]),
        ("work_scope", {"project_ids": ["project"]}),
        ("required_checks", ["has_source_evidence"]),
        ("limits", {"expires_at": 4102444800, "max_acceptances": 2}),
    ):
        changed = copy.deepcopy(raw)
        changed["payload"]["metadata"]["auto_accept"][key] = value
        assert _policy_fingerprint(changed) != before
    current = db.get_schedule(routine["id"])
    moved = copy.deepcopy(current["payload"])
    moved["metadata"]["product_id"] = "another-product"
    db.update_schedule(routine["id"], payload=moved)
    # Product confinement is checked separately from the policy-content version.
    assert _policy_fingerprint(db.get_schedule(routine["id"])) == before
    with pytest.raises(ValueError, match="revoked"):
        await _check_automatic_policy(db, receipt)
    db.update_schedule(routine["id"], payload=current["payload"])
    assert client.patch(path, json={"auto_accept": False}, headers=fresh).status_code == 200
    with pytest.raises(ValueError, match="revoked"):
        await _check_automatic_policy(db, receipt)


def test_registry_mount_excludes_scheduler_tools_and_nested_executors(tmp_path):
    from agno.team import Team
    from agno.workflow import Step, Workflow

    db = SqliteDb(db_file=str(tmp_path / "mount.db"))
    scheduled = Agent(id="scheduled", tools=[SchedulerTools(db)])
    ordinary = Agent(id="ordinary")
    nested = Team(id="nested", members=[scheduled])
    workflow = Workflow(id="scheduled-flow", steps=[Step(name="schedule", agent=scheduled)])
    os = AgentOS(
        db=db,
        registry=Registry(agents=[ordinary, scheduled], teams=[nested], workflows=[workflow]),
        company=CompanyConfig(),
        telemetry=False,
    )
    with TestClient(os.get_app()) as client:
        response = client.get("/agents")
        assert response.status_code == 200
        assert "ordinary" in response.text and "scheduled" not in response.text
        assert client.get("/agents/scheduled").status_code == 404
    assert not os.teams and not os.workflows
    db.close()


@pytest.mark.parametrize("generic", [False, True])
def test_project_completion_policy_requires_projects_write(system, generic):
    import copy

    client, db, os, queue = system
    scopes = SCOPES + ["routines:write", "routines:read", "schedules:write", "schedules:read"]
    product = client.post("/company/products", json={"name": "Docs"}, headers=headers()).json()
    policy = {"executor_type": "agent", "executor_id": "writer", "limits": {"expires_at": 4102444800}}
    response = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="refresh",
            template="refresh",
            executor_type="agent",
            executor_id="writer",
            cron_expr="0 * * * *",
            auto_accept=policy,
        ),
        headers=headers(scopes=scopes),
    )
    assert response.status_code == 201, response.text
    routine = response.json()
    before = db.get_schedule(routine["id"])
    policy["complete_projects"] = True
    if generic:
        payload = copy.deepcopy(before["payload"])
        payload["metadata"]["auto_accept"] = policy
        path, body = "/schedules/" + routine["id"], {"payload": payload}
        assert client.patch(path, json=body, headers=headers(scopes=scopes)).status_code == 409
        assert client.patch(path, json=body, headers=headers(scopes=scopes + ["projects:write"])).status_code == 409
        assert db.get_schedule(routine["id"]) == before
    path, body = "/company/routines/" + routine["id"], {"auto_accept": policy}
    response = client.patch(path, json=body, headers=headers(scopes=scopes))
    assert response.status_code == 403, response.text
    assert db.get_schedule(routine["id"])["payload"] == before["payload"]
    response = client.patch(path, json=body, headers=headers(scopes=scopes + ["projects:write"]))
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("during_checks", [False, True])
async def test_completion_rechecks_managed_human_permission(managed_system, during_checks):
    from agno.company.routines import _CompanyScheduleExecutor

    client, db, os, queue, authz = managed_system
    scopes = SCOPES + [
        "projects:read",
        "projects:write",
        "routines:read",
        "routines:write",
        "schedules:read",
        "schedules:write",
    ]
    authz.define_role("completer", scopes)
    authz.define_role("without_completion", [scope for scope in scopes if scope != "projects:write"])
    authz.set_role("alice", "completer")
    product = client.post("/company/products", json={"name": "Docs"}, headers=headers()).json()
    manager = CompanyManager(db, os.registry)
    project = manager.create_project(product_id=product["id"], name="Release", user_id="alice")
    project = manager.transition_project(project_id=project["id"], target="active", reason="Start")

    async def revoke(proposal, check_manager):
        authz.set_role("alice", "without_completion")
        return True

    os.company.acceptance_checks["revoke_completion"] = revoke
    policy = {
        "executor_type": "agent",
        "executor_id": "writer",
        "complete_projects": True,
        "limits": {"expires_at": 4102444800},
    }
    if during_checks:
        policy["required_checks"] = ["executor_registered", "revoke_completion"]
    response = client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="refresh",
            template="refresh",
            executor_type="agent",
            executor_id="writer",
            cron_expr="0 * * * *",
            auto_accept=policy,
        ),
        headers=headers(),
    )
    assert response.status_code == 201, response.text
    if not during_checks:
        authz.set_role("alice", "without_completion")
    executor = _CompanyScheduleExecutor(
        os, client.app, base_url="http://test", internal_service_token="company-internal"
    )
    proposal = {
        **project,
        "project_id": project["id"],
        "routine_id": response.json()["id"],
        "evidence": [],
    }
    with pytest.raises(PermissionError, match="projects:write"):
        await executor._accept(proposal, completing=True)
    assert db.get_project(project["id"])["status"] == "active"


def test_pending_routine_retry_rechecks_and_refreshes_human_grant(system, monkeypatch):
    from agno.company.routines import _policy_fingerprint
    from agno.run.authorization import AUTHORIZATION_KEY

    client, db, os, queue = system
    scopes = SCOPES + ["routines:write", "schedules:write"]
    product = client.post("/company/products", json={"name": "Recovery"}, headers=headers()).json()
    body = dict(
        product_id=product["id"],
        name="intake",
        template="intake",
        executor_type="agent",
        executor_id="writer",
        cron_expr="0 * * * *",
        auto_accept={"executor_type": "agent", "executor_id": "writer", "limits": {"expires_at": 4102444800}},
    )
    original = db.add_product_routine

    def interrupted(*args, **kwargs):
        raise RuntimeError("Interrupted linking")

    monkeypatch.setattr(db, "add_product_routine", interrupted)
    failing = TestClient(os.get_app(), raise_server_exceptions=False)
    response = failing.post("/company/routines", json=body, headers=headers(scopes=scopes))
    assert response.status_code == 500
    pending = db.get_schedules()[0][0]
    assert pending["enabled"] is False
    before = _policy_fingerprint(pending)
    monkeypatch.setattr(db, "add_product_routine", original)
    revoked = [scope for scope in scopes if scope != "tasks:write"]
    assert client.post("/company/routines", json=body, headers=headers(scopes=revoked)).status_code == 403
    assert db.get_schedule(pending["id"])["enabled"] is False
    fresh = {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": "alice", "aud": "company-execution", "scopes": scopes, "exp": 4102444800}, SECRET, algorithm="HS256"
        )
    }
    response = client.post("/company/routines", json=body, headers=fresh)
    assert response.status_code == 201, response.text
    current = db.get_schedule(pending["id"])
    assert current["enabled"] is True and db.get_schedules()[1] == 1
    assert _policy_fingerprint(current) == before
    grant = current["payload"]["_agno_company_acceptance"]
    assert grant["user_id"] == "alice"
    assert grant != pending["payload"]["_agno_company_acceptance"]
    assert grant[AUTHORIZATION_KEY] == current["payload"][AUTHORIZATION_KEY]


def test_accepted_execution_preserves_scope_and_excludes_private_state(system):
    client, db, os, queue = system
    path, task = accepted(client)
    response = client.post(
        path + "/transitions", json={"target": "backlog", "reason": "Refine scope"}, headers=headers()
    )
    assert response.status_code == 200, response.text
    brief = "Prepare the local patch and tests. Do not publish, deploy, or use production credentials."
    response = client.patch(path, json={"brief": brief}, headers=headers())
    assert response.status_code == 200, response.text
    before = db.get_task(task["id"])
    denied = client.post(path + "/runs", headers=headers())
    assert denied.status_code == 409, denied.text
    assert db.get_task(task["id"]) == before
    assert asyncio.run(queue.store.list_jobs()) == ([], 0)
    response = client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    response = client.post(path + "/runs", headers=headers())
    assert response.status_code == 202, response.text
    job = asyncio.run(queue.store.get_job(response.json()["run_id"]))
    message = job["payload"]["input"]
    payload = json.loads(message)
    assert payload["brief"] == brief
    assert payload["evidence"] == (task.get("evidence") or [])
    assert set(payload) == {"brief", "wiki", "evidence", "execution_context"}
    assert payload["execution_context"]["stage"] == "accepted_task_execution"
    assert payload["execution_context"]["task_id"] == task["id"]
    assert set(payload["execution_context"]) == {"stage", "task_id", "instructions"}
    assert "restrictions" in payload["execution_context"]["instructions"]
    assert "blocker" in payload["execution_context"]["instructions"]
    assert "accepted_by" not in message
    assert db.get_task(task["id"])["brief"] == brief


@pytest.mark.asyncio
async def test_input_builder_does_not_imply_acceptance(system):
    from agno.company.execution import _task_input

    client, db, os, queue = system
    path, task = accepted(client)
    manager = CompanyManager(db)
    payload = json.loads(
        await _task_input(manager, {**db.get_task(task["id"]), "metadata": {"private_marker": "not-for-executor"}})
    )
    assert set(payload) == {"brief", "wiki", "evidence"}


def test_execution_context_does_not_bypass_input_schema(system):
    from pydantic import BaseModel

    class RequiredInput(BaseModel):
        required_business_field: str

    client, db, os, queue = system
    path, task = accepted(client)
    os.registry.agents[0].input_schema = RequiredInput
    before = db.get_task(task["id"])
    response = client.post(path + "/runs", headers=headers())
    assert response.status_code == 400, response.text
    assert db.get_task(task["id"]) == before
    assert asyncio.run(queue.store.list_jobs()) == ([], 0)
