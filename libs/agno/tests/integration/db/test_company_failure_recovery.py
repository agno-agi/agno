"""Actual enqueue loss, completion read failures, and mixed Mongo/SQL Routine storage."""

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from agno.company.execution import _call, _reconcile_task_run
from agno.company.routines import _AutomationSkip, _manager_call
from agno.db.base import AsyncBaseDb
from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.os import AgentOS, CompanyConfig
from tests.integration.db.test_company_execution_parity import (
    accepted,
    automation,
    execute,
    routine_executor,
    routine_proposal,
    tick,
)
from tests.integration.db.test_company_execution_parity import system as execution_system
from tests.integration.db.test_company_routines_parity import create_routine

system = execution_system


def delete_ticket(worker, run_id):
    table = worker.config.db._get_table("jobs")
    with worker.config.db.Session() as session, session.begin():
        session.execute(table.delete().where(table.c.id == run_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery", ["automation", "http", "cancel"])
@pytest.mark.parametrize("kind,executor_id", [("agent", "writer"), ("team", "editors"), ("workflow", "draft")])
async def test_lost_ticket_after_real_enqueue_is_cancelled_and_retryable(system, recovery, kind, executor_id):
    client, db, worker, _, _ = system
    task = await accepted(client, kind, executor_id)
    path = f"/company/tasks/{task['id']}"
    started = await client.post(path + "/runs")
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    original = await _call(db, "get_task", task["id"])
    assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "PENDING"
    assert (await worker.store.get_job(run_id))["status"] == "queued"
    delete_ticket(worker, run_id)
    executor, schedule = await automation(system)
    if recovery == "automation":
        result = await tick(executor, db)
        assert result["output"]["tasks"][0]["action"] == "reconciled", result
        assert (await _call(db, "get_schedule_runs", schedule["id"]))[1] == 1
    elif recovery == "http":
        response = await client.post(path + "/runs")
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "CANCELLED"
    else:
        response = await client.post(f"/company/runs/{run_id}/cancel")
        assert response.status_code == 200, response.text
    saved = await _call(db, "get_task", task["id"])
    assert saved["result"]["status"] == "CANCELLED", saved
    assert "Queue ticket lost" in saved["result"]["content"]
    assert saved["transitions"] == original["transitions"]
    assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "CANCELLED"
    assert await worker.store.get_job(run_id) is None
    # Reconciliation is idempotent and the automation does not replay the run.
    for _ in range(2):
        assert await executor._tick() == []
    for target, extra in [("backlog", {}), ("ready", {"executor_type": kind, "executor_id": executor_id})]:
        response = await client.post(
            path + "/transitions", json={"target": target, "reason": "Retry lost ticket", **extra}
        )
        assert response.status_code == 200, response.text
    retry = await client.post(path + "/runs", json={"attempt": 2})
    assert retry.status_code == 202, retry.text
    assert retry.json()["session_id"] == original["session_id"]
    assert retry.json()["run_id"] != run_id
    assert (await execute(worker))["status"] == "completed"
    assert (await _call(db, "get_task", task["id"]))["status"] == "in_review"


@pytest.mark.asyncio
async def test_ticketless_pending_recovery_does_not_cancel_live_ticket(system):
    client, db, worker, _, _ = system
    task = await accepted(client)
    response = await client.post(f"/company/tasks/{task['id']}/runs")
    run_id = response.json()["run_id"]
    task = await _call(db, "get_task", task["id"])
    run = await _call(db, "get_run", run_id, deserialize=False)
    assert not await _reconcile_task_run(db, db, task, run, None, worker=worker)
    assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "PENDING"
    assert (await execute(worker))["status"] == "completed"


@pytest.mark.asyncio
async def test_ticketless_pending_cancellation_write_failure_stays_retryable(system, monkeypatch):
    from unittest.mock import AsyncMock, Mock

    client, db, worker, _, _ = system
    task = await accepted(client)
    response = await client.post(f"/company/tasks/{task['id']}/runs")
    run_id = response.json()["run_id"]
    delete_ticket(worker, run_id)
    executor, schedule = await automation(system)
    with monkeypatch.context() as failure:
        mock = AsyncMock if isinstance(db, AsyncBaseDb) else Mock
        failure.setattr(db, "cancel_pending_run", mock(side_effect=RuntimeError("Could not persist cancellation")))
        result = await tick(executor, db)
        assert result["status"] == "failed"
        assert "Could not persist cancellation" in result["error"]
        assert (await _call(db, "get_task", task["id"]))["result"] is None
        assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "PENDING"
    outcomes = await executor._tick()
    assert outcomes[0]["action"] == "reconciled"
    assert (await _call(db, "get_task", task["id"]))["result"]["status"] == "CANCELLED"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["database", "policy"])
async def test_project_completion_failure_history(system, tmp_path, monkeypatch, failure):
    client, db, _, _, _ = system
    task, routine, manager = await routine_proposal(system, tmp_path, template="refresh")
    await _manager_call(manager, "transition_task", task_id=task["id"], target="cancelled", reason="Finished")
    policy = routine["payload"]["metadata"]["auto_accept"]
    policy["complete_projects"] = True
    assert (await client.patch("/company/routines/" + routine["id"], json={"auto_accept": policy})).status_code == 200
    await _manager_call(manager, "refresh", task["product_id"])
    executor, schedule = await automation(system)
    if failure == "database":
        original = db.get_tasks
        error = OperationalError("SELECT tasks", {}, RuntimeError("Project completion database unavailable"))

        def read(*args, **kwargs):
            if kwargs.get("project_id") == task["project_id"]:
                raise error
            return original(*args, **kwargs)

        async def aread(*args, **kwargs):
            if kwargs.get("project_id") == task["project_id"]:
                raise error
            return await original(*args, **kwargs)

        monkeypatch.setattr(db, "get_tasks", aread if isinstance(db, AsyncBaseDb) else read)
    else:

        async def refuse(*args, **kwargs):
            raise _AutomationSkip("Completion budget exhausted")

        monkeypatch.setattr(executor, "_accept", refuse)
    result = await tick(executor, db)
    rows, total = await _call(db, "get_schedule_runs", schedule["id"])
    assert total == (1 if failure == "database" else 0), result
    if failure == "database":
        assert result["status"] == "failed", result
        assert "Project completion database unavailable" in rows[0]["error"]
        assert rows[0]["output"]["tasks"][0]["project_id"] == task["project_id"]
    else:
        assert result["status"] == "success"
    assert (await _call(db, "get_project", task["project_id"]))["status"] == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_routine_apis_with_mongo_schedules_and_sql_company(system, asynchronous, monkeypatch):
    url = os.getenv("AGNO_TEST_MONGO_URL")
    if not url:
        pytest.skip("AGNO_TEST_MONGO_URL is required")
    _, company_db, worker, _, components = system
    cls = AsyncMongoDb if asynchronous else MongoDb
    schedule_db = cls(db_url=url, db_name="company_routines_" + uuid4().hex)
    os_app = AgentOS(
        db=schedule_db,
        agents=[components["writer"]],
        company=CompanyConfig(db=company_db),
        queue=worker.config,
        telemetry=False,
    )
    app = os_app.get_app()
    app.state.queue_worker = worker
    worker.authorization_app = app
    worker._company_schedule_db = schedule_db
    try:
        assert await _call(schedule_db, "get_latest_schedule_runs", []) == {}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            routines = [await create_routine(client) for _ in range(3)]
            first = routines[0]
            path = "/company/routines/" + first["id"]
            assert first["last_run"] is None
            assert (await client.get(path)).json() == first
            app.state.scheduler_executor = await routine_executor((client, schedule_db, worker, os_app, components))
            triggered = await client.post(path + "/trigger")
            assert triggered.status_code == 200, triggered.text
            assert triggered.json()["status"] == "success", triggered.text
            latest = (await client.get(path)).json()["last_run"]
            assert latest["run_id"] == triggered.json()["run_id"]
            assert (await client.post(path + "/pause")).json()["last_run"] == latest
            assert (await client.post(path + "/trigger")).status_code == 409
            assert (await client.post(path + "/resume")).json()["last_run"] == latest
            assert (await client.patch(path, json={"name": "Updated"})).json()["last_run"] == latest
            for index, routine in enumerate(routines):
                for stamp in (10, 20):
                    await _call(
                        schedule_db,
                        "create_schedule_run",
                        dict(
                            id=f"ordered-{index}-{stamp}",
                            schedule_id=routine["id"],
                            triggered_at=2000000000,
                            created_at=stamp,
                            status="running",
                            run_id=f"newest-{stamp}",
                            attempt=1,
                        ),
                    )
            # Count real Mongo aggregate commands, not calls to the public helper.
            collection = await _call(schedule_db, "_get_collection", table_type="schedule_runs")
            collection_type = type(collection)
            aggregate = collection_type.aggregate
            queries = []

            def counted(subject, pipeline, *args, **kwargs):
                if subject.name == collection.name:
                    queries.append(pipeline)
                return aggregate(subject, pipeline, *args, **kwargs)

            monkeypatch.setattr(collection_type, "aggregate", counted)
            for limit in (1, 3):
                queries.clear()
                listed = await client.get("/company/routines", params={"limit": limit})
                assert listed.status_code == 200, listed.text
                assert len(listed.json()["data"]) == limit
                assert all(row["last_run"]["run_id"] == "newest-20" for row in listed.json()["data"])
                assert len(queries) == 1, queries
            assert await _call(schedule_db, "get_latest_schedule_runs", ["unknown"]) == {}
    finally:
        if asynchronous:
            await schedule_db.db_client.drop_database(schedule_db.db_name)
        else:
            schedule_db.db_client.drop_database(schedule_db.db_name)
        await _call(schedule_db, "close")


@pytest.mark.asyncio
async def test_pending_recovery_respects_session_owner(system):
    from fastapi import HTTPException

    from agno.db.base import SessionType

    client, db, worker, _, _ = system
    task = await accepted(client)
    started = await client.post(f"/company/tasks/{task['id']}/runs")
    run_id = started.json()["run_id"]
    delete_ticket(worker, run_id)
    reserved = await _call(db, "get_task", task["id"])
    session = await _call(db, "get_session", task["session_id"], session_type=SessionType.AGENT)
    session.user_id = "session-owner"
    await _call(db, "upsert_session", session)
    run = await _call(db, "get_run", run_id, deserialize=False)
    with pytest.raises(HTTPException) as exc:
        await _reconcile_task_run(db, db, reserved, run, "another-user", worker=worker)
    assert exc.value.status_code == 404
    assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "PENDING"
    assert (await _call(db, "get_task", task["id"]))["result"] is None


@pytest.mark.asyncio
async def test_pending_observation_does_not_cancel_a_run_that_started(system):
    from agno.run import RunStatus

    client, db, worker, _, _ = system
    task = await accepted(client)
    started = await client.post(f"/company/tasks/{task['id']}/runs")
    run_id = started.json()["run_id"]
    reserved = await _call(db, "get_task", task["id"])
    observed = await _call(db, "get_run", run_id, deserialize=False)
    current = await _call(db, "get_run", run_id)
    current.status = RunStatus.running
    await _call(db, "upsert_run", current, session_id=task["session_id"])
    delete_ticket(worker, run_id)
    assert not await _reconcile_task_run(db, db, reserved, observed, None, worker=worker)
    assert observed["status"] == "RUNNING"
    assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "RUNNING"
    assert (await _call(db, "get_task", task["id"]))["result"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery", ["backlog_cancel", "ready_cancel", "ready_http", "ready_automation"])
async def test_ticket_lost_before_withdrawal_and_reacceptance(system, recovery):
    client, db, worker, _, _ = system
    task = await accepted(client)
    path = f"/company/tasks/{task['id']}"
    started = await client.post(path + "/runs")
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    delete_ticket(worker, run_id)
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Revise brief"})
    ).status_code == 200
    if recovery == "backlog_cancel":
        cancelled = await client.post(f"/company/runs/{run_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "CANCELLED"
    ready = await client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Accept again", "executor_type": "agent", "executor_id": "writer"},
    )
    assert ready.status_code == 200, ready.text
    if recovery == "ready_cancel":
        cancelled = await client.post(f"/company/runs/{run_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "CANCELLED"
    if recovery == "ready_automation":
        executor, _ = await automation(system)
        result = await tick(executor, db)
        assert result["status"] == "success", result
        assert result["output"]["tasks"][0]["action"] == "submitted", result
    else:
        retry = await client.post(path + "/runs", json={"attempt": 2})
        assert retry.status_code == 202, retry.text
    assert (await _call(db, "get_run", run_id, deserialize=False))["status"] == "CANCELLED"
    assert (await execute(worker))["status"] == "completed"
    saved = await _call(db, "get_task", task["id"])
    assert saved["status"] == "in_review" and saved["session_id"] == task["session_id"]
    assert saved["transitions"][-2]["attempt"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["ERROR", "COMPLETED", "CANCELLED", "RUNNING", "PAUSED"])
@pytest.mark.parametrize("recovery", ["automation", "http"])
async def test_pending_cancellation_preserves_concurrent_worker_status(system, monkeypatch, winner, recovery):
    import asyncio
    from unittest.mock import AsyncMock

    from agno.run.base import RunStatus
    from agno.run.status_persist import apersist_run_status

    client, db, worker, _, _ = system
    task = await accepted(client)
    path = f"/company/tasks/{task['id']}/runs"
    started = await client.post(path)
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert job["id"] == run_id and job["attempt"] == 1
    component = await worker._aresolve_job_component(job)
    await apersist_run_status(
        component,
        "agent",
        session_id=task["session_id"],
        run_id=run_id,
        fields={"queue_attempt": job["attempt"]},
        user_id=job.get("user_id"),
        expected_attempt=job["attempt"],
    )
    delete_ticket(worker, run_id)
    pending = await _call(db, "get_run", run_id)
    assert pending.status == RunStatus.pending
    original = db.cancel_pending_run
    advanced = False
    loop = asyncio.get_running_loop()
    reason = "The original worker settled this attempt"
    cancel_intent = AsyncMock(wraps=component.acancel_run)
    monkeypatch.setattr(component, "acancel_run", cancel_intent)

    async def advance():
        nonlocal advanced
        assert not advanced
        advanced = True
        if winner in {"ERROR", "CANCELLED"}:
            assert await worker._persist_run_error(job, reason, status=winner.lower())
        else:
            pending.status = RunStatus(winner)
            pending.content = reason
            await _call(db, "upsert_run", pending, session_id=task["session_id"])

    def cancel(*args, **kwargs):
        asyncio.run_coroutine_threadsafe(advance(), loop).result(timeout=10)
        return original(*args, **kwargs)

    async def acancel(*args, **kwargs):
        await advance()
        return await original(*args, **kwargs)

    # Settle after recovery has read Pending and resolved the executor, immediately
    # before the conditional database UPDATE. Use the worker's real error writer.
    monkeypatch.setattr(db, "cancel_pending_run", acancel if isinstance(db, AsyncBaseDb) else cancel)
    executor, _ = await automation(system)
    if recovery == "automation":
        result = await tick(executor, db)
        assert result["status"] == "success", result
        assert result["output"]["tasks"][0]["status"] == winner
    else:
        response = await client.post(path)
        assert response.status_code == 202, response.text
        assert response.json()["status"] == winner
    assert advanced
    cancel_intent.assert_not_awaited()
    stored = await _call(db, "get_run", run_id, deserialize=False)
    saved = await _call(db, "get_task", task["id"])
    assert stored["status"] == stored["run_data"]["status"] == winner
    assert stored["run_data"]["content"] == reason
    if winner in {"ERROR", "COMPLETED", "CANCELLED"}:
        assert saved["result"]["status"] == winner
        assert saved["result"]["content"] == reason
    else:
        assert saved["result"] is None
    assert await worker.store.get_job(run_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["none", "session", "owner"])
async def test_pending_cancellation_is_conditional_and_preserves_run_fields(system, guard):
    client, db, _, _, _ = system
    task = await accepted(client)
    started = await client.post(f"/company/tasks/{task['id']}/runs")
    run_id = started.json()["run_id"]
    run = await _call(db, "get_run", run_id)
    data = {
        **run.to_dict(),
        "metadata": {"preserve": "original"},
        "queue_attempt": 7,
        "content": {"structured": "preserve"},
    }
    await _call(db, "upsert_run", data, session_id=task["session_id"], user_id="owner")
    before = await _call(db, "get_run", run_id, deserialize=False)
    changed = await _call(
        db,
        "cancel_pending_run",
        run_id,
        session_id="other-session" if guard == "session" else task["session_id"],
        user_id="other-owner" if guard == "owner" else "owner",
        reason="Lost ticket",
    )
    after = await _call(db, "get_run", run_id, deserialize=False)
    if guard == "none":
        assert changed
        assert after["status"] == "CANCELLED"
        assert after["run_data"] == {**before["run_data"], "status": "CANCELLED"}
        assert not await _call(
            db,
            "cancel_pending_run",
            run_id,
            session_id=task["session_id"],
            user_id="owner",
            reason="Must not overwrite cancellation",
        )
    else:
        assert not changed
        assert after == before
