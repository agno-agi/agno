"""Replica liveness, owner offboarding, mixed storage and synchronous attention."""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from agno.company.automation_history import _record_task_failures, aautomation_failures
from agno.company.execution import _call, _recover_task
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID, ScheduleRun
from agno.os.authz import Authorization, UserDirectory
from agno.run.cancel import aget_active_runs
from tests.integration.db.test_company_actor_owner_parity import EXECUTORS, company_app
from tests.integration.db.test_company_execution_parity import accepted, automation, execute, tick
from tests.integration.db.test_company_execution_parity import system as execution_system
from tests.integration.db.test_company_failure_recovery import delete_ticket

system = execution_system
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("isolation", [False, True])
async def test_ticketless_checkpoint_on_another_replica_remains_running(system, tmp_path, isolation, monkeypatch):
    _, db, worker, _, components = system
    os_app, app = company_app(db, worker, components, isolation)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = await accepted(client)
        started = await client.post("/company/tasks/" + task["id"] + "/runs")
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    config = {
        "db_file": getattr(db, "db_file", None),
        "async": isinstance(db, AsyncBaseDb),
        "schema": worker.config.db.db_schema,
        "url": "postgresql+psycopg://ai:ai@localhost:5532/ai",
        **{name: str(tmp_path / name) for name in ("started", "release", "tool")},
    }
    log_path = tmp_path / "replica.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "tests.integration.db.company_replica_worker", json.dumps(config)],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(2000):
                if (tmp_path / "started").exists() or process.poll() is not None:
                    break
                await asyncio.sleep(0.01)
            assert (tmp_path / "started").exists(), log_path.read_text()
            assert (tmp_path / "tool").read_text() == "executed once"
            assert run_id in json.loads((tmp_path / "started").read_text())
            assert run_id not in await aget_active_runs()
            delete_ticket(worker, run_id)
            monkeypatch.setattr(worker.store, "enqueue_job", AsyncMock(side_effect=AssertionError("Must not replay")))
            for _ in range(2):
                outcome = await _recover_task(os_app, worker, await _call(db, "get_task", task["id"]))
                assert outcome["status"] == "RUNNING" and outcome["action"] == "observed"
                assert (await _call(db, "get_task", task["id"]))["result"] is None
                assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "RUNNING"
            (tmp_path / "release").touch()
            await asyncio.to_thread(process.wait, timeout=30)
            assert process.returncode == 0, log_path.read_text()
            await _recover_task(os_app, worker, await _call(db, "get_task", task["id"]))
            saved = await _call(db, "get_task", task["id"])
            assert saved["result"]["status"] == "COMPLETED"
            assert saved["status"] == "in_review"
        finally:
            (tmp_path / "release").touch()
            if process.poll() is None:
                process.terminate()
                await asyncio.to_thread(process.wait, timeout=10)


@pytest.mark.parametrize("isolation", [False, True])
@pytest.mark.parametrize("kind,executor_id", EXECUTORS)
async def test_disabled_owner_blocks_new_work_but_allows_collaborator_cancel(
    system, isolation, kind, executor_id, monkeypatch
):
    _, db, worker, _, components = system
    secret = "disabled-owner-regression-secret-at-least-32-bytes"
    common = [f"{r}:{a}" for r in ("products", "projects", "tasks") for a in ("read", "write")] + ["wiki:read"]
    auth = Authorization(verification_keys=[secret], algorithm="HS256")
    os_app, app = company_app(db, worker, components, isolation, auth, UserDirectory(auto_provision=True))

    def headers(user):
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {
                    "sub": user,
                    "aud": "actor-owner",
                    "exp": int(time.time()) + 3600,
                    "scopes": common + ([kind + "s:run"] if user == "bob" else []),
                },
                secret,
                algorithm="HS256",
            )
        }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers("alice")
    ) as client:
        product = (await client.post("/company/products", json={"name": "Product"})).json()
        project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Project"})).json()
        approval = {"target": "active", "reason": "Approved"}
        await client.post("/company/projects/" + project["id"] + "/transitions", json=approval)
        task = (
            await client.post(
                "/company/tasks",
                json={"product_id": product["id"], "project_id": project["id"], "title": "Task", "brief": "Draft"},
            )
        ).json()
        client.headers.update(headers("bob"))
        path = "/company/tasks/" + task["id"]
        ready = {"target": "ready", "reason": "Approve", "executor_type": kind, "executor_id": executor_id}
        assert (await client.post(path + "/transitions", json=ready)).status_code == 200
        first = await client.post(path + "/runs")
        assert first.status_code == 202, first.text
        with monkeypatch.context() as failure:

            def unavailable(*args, **kwargs):
                raise RuntimeError("Lost Task projection")

            failure.setattr(db, "complete_task_run", unavailable)
            await execute(worker)
        assert (await _call(db, "get_run", first.json()["run_id"], deserialize=False))["status"] == "COMPLETED"
        await app.state.user_store.aset_disabled("alice", True, actor="root")
        delete_ticket(worker, first.json()["run_id"])
        recovered = await _recover_task(os_app, worker, await _call(db, "get_task", task["id"]))
        assert recovered["action"] == "reconciled"
        assert (await _call(db, "get_task", task["id"]))["result"]["status"] == "COMPLETED"
        before = await _call(db, "get_task", task["id"])
        refused = await client.post(path + "/runs", json={"attempt": 2})
        assert refused.status_code == 403, refused.text
        assert "Schedule owner is disabled" in refused.text
        assert await _call(db, "get_task", task["id"]) == before
        for transition in [{"target": "backlog", "reason": "Retry"}, ready]:
            assert (await client.post(path + "/transitions", json=transition)).status_code == 200
        scheduler, schedule = await automation((client, db, worker, os_app, components))
        for expected_status in ("failed", "success"):
            await _call(db, "update_schedule", schedule["id"], next_run_at=0)
            assert (await tick(scheduler, db))["status"] == expected_status
        attention = (await client.get("/company/attention")).json()
        assert attention["automation_failures"][0]["count"] == 1
        assert "disabled" in attention["automation_failures"][0]["reason"]
        assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"
        assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None
        await app.state.user_store.aset_disabled("alice", False, actor="root")
        assert (await client.post(path + "/transitions", json=ready)).status_code == 200
        second = await client.post(path + "/runs", json={"attempt": 2})
        assert second.status_code == 202, second.text
        await app.state.user_store.aset_disabled("alice", True, actor="root")
        cancelled = await client.post("/company/runs/" + second.json()["run_id"] + "/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert (await _call(db, "get_task", task["id"]))["result"]["status"] == "CANCELLED"


@pytest.mark.parametrize("isolation", [False, True])
async def test_company_owner_directory_failure_is_closed(system, isolation, monkeypatch):
    from agno.company.execution import _task_transport
    from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER

    _, db, worker, _, components = system
    _, app = company_app(
        db,
        worker,
        components,
        isolation,
        Authorization(verification_keys=["secret"], algorithm="HS256"),
        UserDirectory(),
    )
    monkeypatch.setattr(app.state.user_store, "ais_disabled", AsyncMock(side_effect=RuntimeError("Directory offline")))
    token = _task_transport.set(("POST", "/agents/writer/runs", "alice"))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/agents/writer/runs",
                headers={"Authorization": "Bearer test", SCHEDULE_OWNER_HEADER: "alice"},
                data={"message": "Draft", "background": "true", "stream": "false"},
            )
    finally:
        _task_transport.reset(token)
    assert response.status_code == 503, response.text
    assert "User directory unavailable" in response.text


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_refresh_with_mongo_history_continues_completion_proposals(system, asynchronous):
    url = os.getenv("AGNO_TEST_MONGO_URL")
    if not url:
        pytest.skip("AGNO_TEST_MONGO_URL is required")
    client, db, _, _, _ = system
    task = await accepted(client)
    await _call(db, "transition_task", task["id"], "cancelled", "No work needed")
    schedule_db = (AsyncMongoDb if asynchronous else MongoDb)(db_url=url, db_name="company_refresh_" + uuid4().hex)
    manager = (AsyncCompanyManager if isinstance(db, AsyncBaseDb) else CompanyManager)(db, schedule_db=schedule_db)
    now = int(time.time())
    try:
        for name, schedule, age, complete in [
            ("old", COMPANY_AUTOMATION_SCHEDULE_ID, 31, True),
            ("recent", COMPANY_AUTOMATION_SCHEDULE_ID, 29, True),
            ("running", COMPANY_AUTOMATION_SCHEDULE_ID, 31, False),
            ("routine", "another-schedule", 31, True),
        ]:
            await _call(
                schedule_db,
                "create_schedule_run",
                ScheduleRun(
                    id=name,
                    schedule_id=schedule,
                    triggered_at=now - age * 86400,
                    completed_at=now - age * 86400 if complete else None,
                    status="success" if complete else "running",
                ).to_dict(),
            )
        result = await _call(manager, "refresh", task["product_id"])
        assert result["deleted_automation_runs"] == 1
        assert result["completion_proposals"][0]["project_id"] == task["project_id"]
        assert {
            row["id"] for row in (await _call(schedule_db, "get_schedule_runs", COMPANY_AUTOMATION_SCHEDULE_ID))[0]
        } == {"recent", "running"}
        assert (await _call(schedule_db, "get_schedule_runs", "another-schedule"))[1] == 1
        assert (await _call(manager, "refresh", task["product_id"]))["deleted_automation_runs"] == 0
    finally:
        if asynchronous:
            await schedule_db.db_client.drop_database(schedule_db.db_name)
        else:
            schedule_db.db_client.drop_database(schedule_db.db_name)
        await _call(schedule_db, "close")


@pytest.mark.parametrize("system", ["sqlite", "postgres"], indirect=True)
async def test_sync_attention_inside_event_loop_with_paginated_history(system):
    client, db, _, _, _ = system
    manager = CompanyManager(db)
    assert "automation_failures" not in manager.attention()
    task = await accepted(client)
    await automation(system)
    outcomes = [{"task_id": task["id"], "status": "failed", "reason": "Executor offline"}]
    for _ in range(2):
        await _record_task_failures(db, db, outcomes)
    # Push the active diagnostic past the first page without changing its Task state.
    for index in range(101):
        db.create_schedule_run(
            ScheduleRun(
                id=str(index),
                schedule_id=COMPANY_AUTOMATION_SCHEDULE_ID,
                triggered_at=int(time.time()) + 10,
                status="success",
            ).to_dict()
        )
    expected = [{"task_id": task["id"], "reason": "Executor offline", "count": 2}]
    assert manager.attention()["automation_failures"] == expected
    assert manager.attention(task["product_id"])["automation_failures"] == expected
    assert await aautomation_failures(db, db) == expected
    assert "automation_failures" not in manager.attention("another-product")
    await _call(db, "transition_task", task["id"], "backlog", "Replan")
    assert "automation_failures" not in manager.attention()
