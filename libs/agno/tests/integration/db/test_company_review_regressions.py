import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

from agno.company.execution import _call
from agno.db.base import AsyncBaseDb
from agno.scheduler.manager import ScheduleManager
from tests.integration.db.test_company_execution_parity import accepted, automation, tick
from tests.integration.db.test_company_execution_parity import system as execution_system

system = execution_system


@pytest.mark.asyncio
async def test_ready_task_storage_error_is_persisted(system, monkeypatch):
    client, db, worker, os, components = system
    await accepted(client)
    executor, schedule = await automation(system)
    error = OperationalError("SELECT tasks", {}, RuntimeError("connection lost while reading Task"))

    def fail(*args, **kwargs):
        raise error

    async def afail(*args, **kwargs):
        raise error

    monkeypatch.setattr(db, "get_task", afail if isinstance(db, AsyncBaseDb) else fail)
    result = await tick(executor, db)
    rows, count = await _call(db, "get_schedule_runs", schedule["id"])
    assert count == 1, {"history_count": count, "tick": result}
    assert "connection lost while reading Task" in str(rows[0]), rows


@pytest.mark.asyncio
async def test_last_run_exposes_new_execution_in_same_second(system, monkeypatch):
    from agno.scheduler.executor import ScheduleExecutor, _active_schedule_run
    from tests.integration.db.test_company_routines_parity import create_routine

    client, db, worker, os, components = system
    routine = await create_routine(client)
    schedule = await _call(db, "get_schedule", routine["id"])
    executor = ScheduleExecutor(base_url="http://test", internal_service_token="offline-review")
    record_ids = iter([UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"), UUID("00000000-0000-4000-8000-000000000000")])
    monkeypatch.setattr("agno.scheduler.run_id.uuid4", lambda: next(record_ids))
    monkeypatch.setattr("agno.scheduler.run_id._last_timestamp", 0)
    monkeypatch.setattr("agno.scheduler.executor.time", SimpleNamespace(time=lambda: 1800000000))
    monkeypatch.setattr("agno.scheduler.run_id.time", SimpleNamespace(time_ns=lambda: 1800000000000000000))
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = 0

    async def endpoint(sched):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"status": "success", "run_id": "previous-run", "session_id": "previous-session"}
        store, record_id = _active_schedule_run.get()
        await _call(store, "update_schedule_run", record_id, run_id="new-running-run", session_id="new-session")
        started.set()
        await finish.wait()
        return {"status": "success", "run_id": "new-running-run", "session_id": "new-session"}

    monkeypatch.setattr(executor, "_call_endpoint", endpoint)
    await executor.execute(schedule, db, release_schedule=False)
    second = asyncio.create_task(executor.execute(schedule, db, release_schedule=False))
    try:
        await asyncio.wait_for(started.wait(), 5)
        latest = (await client.get("/company/routines/" + routine["id"])).json()["last_run"]
        assert latest["run_id"] == "new-running-run", latest
    finally:
        finish.set()
        await second


@pytest.mark.asyncio
async def test_enabled_update_rearms_schedule(system):
    _, db, _, _, _ = system
    manager = ScheduleManager(db)
    schedule = await manager.acreate(
        name="enable-gap", cron="0 9 * * *", endpoint="/agents/writer/runs", enabled_on_create=False
    )
    edited = await manager.aupdate(schedule.id, cron_expr="0 10 * * *")
    assert edited.next_run_at is None
    enabled = await manager.aupdate(schedule.id, enabled=True)
    assert enabled.enabled and enabled.next_run_at is not None
    repaired = await manager.aenable(schedule.id)
    assert repaired.next_run_at is not None


@pytest.mark.asyncio
async def test_expected_refusal_keeps_history_quiet(system):
    client, db, worker, _, _ = system
    task = await accepted(client)
    path = "/company/tasks/" + task["id"]
    started = await client.post(path + "/runs")
    assert started.status_code == 202, started.text
    moved = await client.post(path + "/transitions", json={"target": "backlog", "reason": "Rescope"})
    assert moved.status_code == 200, moved.text
    ready = await client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Reaccept", "executor_type": "agent", "executor_id": "writer"},
    )
    assert ready.status_code == 200, ready.text
    executor, schedule = await automation(system)
    for _ in range(2):
        await _call(db, "update_schedule", schedule["id"], next_run_at=0)
        result = await tick(executor, db)
        assert result["status"] == "success", result
    rows, count = await _call(db, "get_schedule_runs", schedule["id"])
    assert count == 0, rows
    expected = "previous Task run is still active"
    assert expected.lower() in str(result).lower(), result
    assert (await client.get(path)).json()["status"] == "ready"


@pytest.mark.asyncio
async def test_sync_enabled_update_rearms_schedule(system):
    _, db, _, _, _ = system
    manager = ScheduleManager(db)
    schedule = await asyncio.to_thread(
        manager.create,
        name="sync-enable-gap",
        cron="0 9 * * *",
        endpoint="/agents/writer/runs",
        enabled_on_create=False,
    )
    edited = await asyncio.to_thread(manager.update, schedule.id, cron_expr="0 10 * * *")
    assert edited.next_run_at is None
    enabled = await asyncio.to_thread(manager.update, schedule.id, enabled=True)
    assert enabled.enabled and enabled.next_run_at is not None
    manual = await asyncio.to_thread(manager.update, schedule.id, cron_expr="", enabled=False)
    assert manual.next_run_at is None
    assert (await asyncio.to_thread(manager.update, schedule.id, enabled=True)).next_run_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("http_denial", [False, True])
async def test_denied_ready_task_returns_to_backlog_once(system, monkeypatch, http_denial):
    from fastapi import HTTPException

    client, db, worker, _, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    if http_denial:

        async def deny(task):
            raise HTTPException(403, "Missing agents:run permission")

        monkeypatch.setattr(executor, "_dispatch", deny)
    else:

        class DeniedAuthority:
            async def arequire(self, *args):
                raise PermissionError("Missing agents:run permission")

        monkeypatch.setattr("agno.os.authz.run_context.restore_authorization", lambda *args: DeniedAuthority())
    result = await tick(executor, db)
    assert result["status"] == "failed", result
    saved = await _call(db, "get_task", task["id"])
    assert saved["status"] == "backlog" and saved["job_id"] is None
    assert "agents:run" in saved["transitions"][-1]["reason"]
    assert (await client.get("/company/attention")).json()["proposals"] == 1
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    assert (await tick(executor, db))["status"] == "success"
    assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 1
    assert await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_endpoint_only_python_update_checks_target(system, monkeypatch, asynchronous):
    from unittest.mock import AsyncMock, Mock

    _, db, _, _, _ = system
    manager = ScheduleManager(db)
    schedule = await manager.acreate(name="endpoint-check", cron="", endpoint="/agents/writer/runs")
    check = AsyncMock() if asynchronous else Mock()
    monkeypatch.setattr(
        "agno.scheduler.manager." + ("arequire_schedule_target" if asynchronous else "require_schedule_target"), check
    )
    if asynchronous:
        await manager.aupdate(schedule.id, endpoint="/teams/editors/runs")
        check.assert_awaited_once_with("/teams/editors/runs", "POST")
    else:
        await asyncio.to_thread(manager.update, schedule.id, endpoint="/teams/editors/runs")
        check.assert_called_once_with("/teams/editors/runs", "POST")


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", [False, True])
async def test_managed_role_revocation_withdraws_ready_task(system, tmp_path, isolation):
    import time

    import jwt
    from httpx import ASGITransport, AsyncClient

    from agno.db.sqlite import SqliteDb
    from agno.os import AgentOS, CompanyConfig
    from agno.os.authz import Authorization
    from agno.registry import Registry

    _, db, worker, _, components = system
    auth_db = SqliteDb(db_file=str(tmp_path / "revocation.db"))
    secret = "ready-revocation-tests-secret-at-least-32-bytes"
    scopes = [
        f"{resource}:{action}" for resource in ("products", "projects", "tasks") for action in ("read", "write")
    ] + ["agents:writer:run", "wiki:read"]
    authz = Authorization(db=auth_db, verification_keys=[secret], algorithm="HS256")
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("runner", scopes)
    authz.define_role("without_run", [scope for scope in scopes if scope != "agents:writer:run"])
    authz.seed(admin="root")
    authz.assign("alice", "runner")
    agent_os = AgentOS(
        id="ready-revocation",
        db=db,
        registry=Registry(agents=[components["writer"]]),
        company=CompanyConfig(),
        queue=worker.config,
        telemetry=False,
        user_isolation=isolation,
        authorization=authz,
    )
    app = agent_os.get_app()
    app.state.queue_worker = worker
    app.state.internal_service_token = "test"
    worker.authorization_app = app
    token = jwt.encode(
        {"sub": "alice", "aud": "ready-revocation", "exp": int(time.time()) + 3600}, secret, algorithm="HS256"
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers={"Authorization": "Bearer " + token}
        ) as client:
            task = await accepted(client)
            executor, schedule = await automation((client, db, worker, agent_os, components))
            await authz.aset_role("alice", "without_run")
            assert (await tick(executor, db))["status"] == "failed"
            saved = await _call(db, "get_task", task["id"])
            assert saved["status"] == "backlog" and saved["job_id"] is None
            assert "permission" in saved["transitions"][-1]["reason"].lower()
            assert (await client.get("/company/attention")).json()["proposals"] == 1
            await _call(db, "update_schedule", schedule["id"], next_run_at=0)
            assert (await tick(executor, db))["status"] == "success"
            assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 1
    finally:
        auth_db.close()
