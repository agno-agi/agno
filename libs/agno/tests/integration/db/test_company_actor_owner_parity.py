"""Actor authority, session identity and controlled recovery errors across SQL stores."""

import asyncio
import time
from unittest.mock import AsyncMock

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from agno.company.execution import _call
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from tests.integration.db.test_company_execution_parity import accepted, automation, execute
from tests.integration.db.test_company_execution_parity import system as execution_system
from tests.integration.db.test_company_failure_recovery import delete_ticket

system = execution_system
pytestmark = [pytest.mark.asyncio, pytest.mark.parametrize("isolation", [False, True])]
EXECUTORS = [("agent", "writer"), ("team", "editors"), ("workflow", "draft")]


def company_app(db, worker, components, isolation, authorization=None, user_directory=None):
    os = AgentOS(
        id="actor-owner",
        db=db,
        agents=[components["writer"]],
        teams=[components["editors"]],
        workflows=[components["draft"]],
        company=CompanyConfig(),
        queue=worker.config,
        authorization=authorization,
        user_directory=user_directory,
        user_isolation=isolation,
        telemetry=False,
    )
    app = os.get_app()
    app.state.queue_worker = worker
    app.state.internal_service_token = "test"
    worker.authorization_app = app
    return os, app


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("kind,executor_id", EXECUTORS)
async def test_owner_without_run_scope_can_delegate_start_and_cancel(
    system, tmp_path, isolation, managed, kind, executor_id
):
    _, db, worker, _, components = system
    secret = "actor-owner-regression-secret-at-least-32-bytes"
    common = [f"{r}:{a}" for r in ("products", "projects", "tasks") for a in ("read", "write")] + ["wiki:read"]
    runner = common + [kind + "s:run"]
    auth_db = SqliteDb(db_file=str(tmp_path / "actors.db"))
    auth = Authorization(db=auth_db if managed else None, verification_keys=[secret], algorithm="HS256")
    if managed:
        auth.define_role("admin", ["agent_os:admin"])
        auth.define_role("writer", common)
        auth.define_role("runner", runner)
        auth.seed(admin="root")
        auth.assign("alice", "writer")
        auth.assign("bob", "runner")

    def headers(user):
        claims = {"sub": user, "aud": "actor-owner", "exp": int(time.time()) + 3600}
        if not managed:
            claims["scopes"] = runner if user == "bob" else common
        return {"Authorization": "Bearer " + jwt.encode(claims, secret, algorithm="HS256")}

    os, app = company_app(db, worker, components, isolation, auth)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers("alice")
        ) as client:
            product = (await client.post("/company/products", json={"name": "Product"})).json()
            project = (
                await client.post("/company/projects", json={"product_id": product["id"], "name": "Project"})
            ).json()
            task = (
                await client.post(
                    "/company/tasks",
                    json={"product_id": product["id"], "project_id": project["id"], "title": "Task", "brief": "Draft"},
                )
            ).json()
            path = "/company/tasks/" + task["id"]
            response = await client.post(
                path + "/transitions",
                headers=headers("bob"),
                json={"target": "ready", "reason": "Approve", "executor_type": kind, "executor_id": executor_id},
            )
            assert response.status_code == 200, response.text
            assert (await client.post(path + "/runs")).status_code == 403
            first = await client.post(path + "/runs", headers=headers("bob"))
            assert first.status_code == 202, first.text
            assert (await execute(worker))["status"] == "completed"
            second = await client.post(path + "/runs", headers=headers("bob"), json={"attempt": 2})
            assert second.status_code == 202, second.text
            run_id = second.json()["run_id"]
            assert second.json()["session_id"] == first.json()["session_id"]
            before = await _call(db, "get_task", task["id"])
            refused = await client.post("/company/runs/" + run_id + "/cancel")
            assert refused.status_code == 403, refused.text
            assert (await worker.store.get_job(run_id))["status"] == "queued"
            assert await _call(db, "get_task", task["id"]) == before
            cancelled = await client.post("/company/runs/" + run_id + "/cancel", headers=headers("bob"))
            assert cancelled.status_code == 200, cancelled.text
            assert (await worker.store.get_job(run_id))["status"] == "cancelled"
            assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
            current = await _call(db, "get_task", task["id"])
            assert current["result"]["status"] == "CANCELLED"
            assert current["transitions"][-1]["started_by"] == "bob"
            assert (await _call(db, "get_run", run_id, deserialize=False))["user_id"] == "alice"

            # A regular scheduler transport still checks the owner's own authority.
            if managed:
                from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER

                direct = await client.post(
                    f"/{kind}s/{executor_id}/runs",
                    headers={
                        "Authorization": "Bearer " + app.state.internal_service_token,
                        SCHEDULE_OWNER_HEADER: "alice",
                    },
                    data={"message": "Not a Company handoff", "background": "true", "stream": "false"},
                )
                assert direct.status_code == 403, direct.text
                assert "Schedule owner is not authorized" in direct.text

            for target, extra in [("backlog", {}), ("ready", {"executor_type": kind, "executor_id": executor_id})]:
                response = await client.post(
                    path + "/transitions", headers=headers("bob"), json={"target": target, "reason": "Retry", **extra}
                )
                assert response.status_code == 200, response.text
            scheduler, _ = await automation((client, db, worker, os, components))
            outcome = await scheduler._tick()
            assert outcome[0]["action"] == "submitted", outcome
            assert (await execute(worker))["status"] == "completed"
            current = await _call(db, "get_task", task["id"])
            assert current["transitions"][-2]["started_by"] == "bob"
            assert (await _call(db, "get_run", current["job_id"], deserialize=False))["user_id"] == "alice"
    finally:
        auth_db.close()


@pytest.mark.parametrize("kind,executor_id", EXECUTORS)
async def test_unowned_task_persists_executor_default_through_revision_recovery_and_cancel(
    system, isolation, monkeypatch, kind, executor_id
):
    _, db, worker, _, components = system
    components[executor_id].user_id = "assistant"
    os, app = company_app(db, worker, components, isolation)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = await accepted(client, kind, executor_id)
        assert task["user_id"] is None
        path = "/company/tasks/" + task["id"] + "/runs"
        first = await client.post(path)
        assert first.status_code == 202, first.text
        assert (await execute(worker))["status"] == "completed"
        second = await client.post(path, json={"attempt": 2})
        assert second.status_code == 202, second.text
        assert second.json()["session_id"] == first.json()["session_id"]
        with monkeypatch.context() as failure:

            def unavailable(*args, **kwargs):
                raise RuntimeError("Lost projection")

            failure.setattr(
                db,
                "complete_task_run",
                AsyncMock(side_effect=unavailable)
                if asyncio.iscoroutinefunction(db.complete_task_run)
                else unavailable,
            )
            await execute(worker)
        assert (await _call(db, "get_run", second.json()["run_id"], deserialize=False))["status"] == "COMPLETED"
        delete_ticket(worker, second.json()["run_id"])
        recovered = await client.post(path, json={"attempt": 2})
        assert recovered.status_code == 202, recovered.text
        current = await _call(db, "get_task", task["id"])
        assert current["result"]["status"] == "COMPLETED"
        for response in (first, second):
            assert (await _call(db, "get_run", response.json()["run_id"], deserialize=False))["user_id"] == "assistant"
        session = await _call(db, "get_session", task["session_id"], session_type=SessionType(kind), deserialize=False)
        assert session["user_id"] == "assistant"
        components[executor_id].user_id = "changed-default"
        third = await client.post(path, json={"attempt": 3})
        assert third.status_code == 202, third.text
        current = await _call(db, "get_task", task["id"])
        assert current["transitions"][-1]["session_user_id"] == "assistant"
        assert current["transitions"][-1]["started_by"] is None
        response = await client.post("/company/runs/" + third.json()["run_id"] + "/cancel")
        assert response.status_code == 200, response.text
        assert (await _call(db, "get_task", task["id"]))["result"]["status"] == "CANCELLED"


@pytest.mark.parametrize("operation", ["start", "cancel"])
@pytest.mark.parametrize("fault,status", [("owner", 409), ("session", 409), ("store", 503)])
async def test_identity_and_storage_faults_return_controlled_errors(
    system, isolation, monkeypatch, operation, fault, status
):
    _, db, worker, _, components = system
    os, app = company_app(db, worker, components, isolation)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = await accepted(client)
        started = await client.post("/company/tasks/" + task["id"] + "/runs")
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        before = await _call(db, "get_task", task["id"])
        if fault == "store":
            monkeypatch.setattr(os, "dbs", {})
        else:
            original = db.get_run

            async def corrupted(*args, **kwargs):
                row = (
                    await original(*args, **kwargs)
                    if asyncio.iscoroutinefunction(original)
                    else original(*args, **kwargs)
                )
                if row is not None and kwargs.get("deserialize") is False:
                    row = {**row, "user_id" if fault == "owner" else "session_id": "conflicting-identity"}
                return row

            if asyncio.iscoroutinefunction(original):
                monkeypatch.setattr(db, "get_run", corrupted)
            else:
                monkeypatch.setattr(db, "get_run", lambda *args, **kwargs: asyncio.run(corrupted(*args, **kwargs)))
        if operation == "start":
            delete_ticket(worker, run_id)
            path = "/company/tasks/" + task["id"] + "/runs"
        else:
            path = "/company/runs/" + run_id + "/cancel"
        response = await client.post(path)
        assert response.status_code == status, response.text
        assert await _call(db, "get_task", task["id"]) == before
        if operation == "cancel":
            assert (await worker.store.get_job(run_id))["status"] == "queued"


async def test_ticketless_recovery_with_unavailable_executor_returns_503(system, isolation, monkeypatch):
    _, db, worker, _, components = system
    _, app = company_app(db, worker, components, isolation)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = await accepted(client)
        started = await client.post("/company/tasks/" + task["id"] + "/runs")
        run_id = started.json()["run_id"]
        delete_ticket(worker, run_id)
        monkeypatch.setattr(worker, "_aresolve_job_component", AsyncMock(return_value=None))
        response = await client.post("/company/tasks/" + task["id"] + "/runs")
        assert response.status_code == 503, response.text
        assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "PENDING"
