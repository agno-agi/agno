"""Model-free sandbox admission and retry regressions on all four Company stores."""

from types import SimpleNamespace

import pytest
import pytest_asyncio

from agno.company.execution import _call, _project_run
from agno.job_queue import QueueConfig
from agno.sandbox import Repository
from agno.sandbox.checkpoint import FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent
from tests.integration.db.test_company_execution_parity import accepted, system  # noqa: F401, F811

URL = "https://github.com/octocat/Hello-World"
PIN = {"url": URL, "branch": "master", "commit": "a" * 40}


@pytest_asyncio.fixture
async def sandbox_system(system, monkeypatch, tmp_path):  # noqa: F811
    import agno.os.event_streams as streams
    import agno.run.cancel as cancel

    # Queue configuration can replace process defaults; restore them after each case.
    monkeypatch.setattr(streams, "_event_stream", streams._event_stream)
    monkeypatch.setattr(streams, "_event_stream_explicitly_set", streams._event_stream_explicitly_set)
    monkeypatch.setattr(cancel, "_cancellation_manager", cancel._cancellation_manager)
    monkeypatch.setattr(cancel, "_cancellation_manager_explicitly_set", cancel._cancellation_manager_explicitly_set)
    client, db, worker, os, components = system
    agent = FixtureAgent(
        id="engineer",
        db=worker.config.db,
        sandbox=DockerSandbox(
            "unused", env={"AGNO_SANDBOX_TEST_RUNTIME": "1"}, checkpoints=FileCheckpointStore(tmp_path / "checkpoints")
        ),
        repository=Repository(URL, "master"),
    )
    os.agents.append(agent)
    os.registry.agents.append(agent)
    os.dbs[agent.db.id] = [agent.db]
    components["engineer"] = agent
    worker.config = QueueConfig(durable=True, db=worker.config.db, redis="redis://localhost:6379/0", max_attempts=1)
    yield client, db, worker, os, agent


async def engineering_task(client, db):
    task = await accepted(client)
    path = "/company/tasks/" + task["id"]
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Select engineer"})
    ).status_code == 200
    await _call(
        db,
        "create_source",
        {"id": task["id"], "product_id": task["product_id"], "type": "git", "reference": URL, "created_at": 1},
    )
    ready = await client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "engineer"},
    )
    assert ready.status_code == 200, ready.text
    return ready.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_status", ["failed", "cancelled"])
async def test_successful_retry_establishes_missing_pin(sandbox_system, first_status):
    client, db, worker, _, agent = sandbox_system
    task = await engineering_task(client, db)
    path = "/company/tasks/" + task["id"]
    first = await client.post(path + "/runs")
    assert first.status_code == 202, first.text
    job = await worker.store.get_job(first.json()["run_id"])
    await _project_run(worker, job, first_status, "Transient first attempt")
    await worker.store.cancel_job(job["id"])
    failed = await _call(db, "get_task", task["id"])
    assert failed["metadata"] is None
    second = await client.post(path + "/runs", json={"attempt": 2})
    assert second.status_code == 202, second.text
    second_job = await worker.store.get_job(second.json()["run_id"])

    async def output(*args, **kwargs):
        return SimpleNamespace(
            status="COMPLETED",
            to_dict=lambda: {
                "run_id": second_job["id"],
                "status": "COMPLETED",
                "content": "Successful retry",
                "metadata": {"sandbox": {"repository": PIN}},
            },
        )

    agent.aget_run_output = output
    await _project_run(worker, second_job, "completed")
    result = await _call(db, "get_task", task["id"])
    assert result["status"] == "in_review"
    assert result["result"]["status"] == "COMPLETED"
    assert result["metadata"]["checkout"] == {"source_id": task["id"], **PIN}
    assert result["session_id"] == failed["session_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["backlog", "reassigned", "archived", "new_reservation"])
async def test_live_job_blocks_after_task_mutation(sandbox_system, mutation):
    client, db, worker, _, _ = sandbox_system
    first = await engineering_task(client, db)
    second = await engineering_task(client, db)
    path = "/company/tasks/" + first["id"]
    response = await client.post(path + "/runs")
    assert response.status_code == 202, response.text
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert job["id"] == response.json()["run_id"]
    second_path = "/company/tasks/" + second["id"] + "/runs"
    assert (await client.post(second_path)).status_code == 409
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Edit work"})
    ).status_code == 200
    if mutation in {"reassigned", "new_reservation"}:
        ready = await client.post(
            path + "/transitions",
            json={"target": "ready", "reason": "New executor", "executor_type": "agent", "executor_id": "writer"},
        )
        assert ready.status_code == 200, ready.text
        if mutation == "new_reservation":
            value = await _call(db, "get_task", first["id"])
            await _call(db, "start_task_run", first["id"], 2, value["transitions"], run_db_id=worker.config.db.id)
    elif mutation == "archived":
        assert (await client.delete(path)).status_code == 204
    blocked = await client.post(second_path)
    assert blocked.status_code == 409 and "live job" in blocked.text, blocked.text
    assert (await worker.store.get_job(job["id"]))["status"] == "running"
    await worker.store.complete_job(job["id"], worker.worker_id, job["attempt"], "cancelled")
    allowed = await client.post(second_path)
    assert allowed.status_code == 202, allowed.text


@pytest.mark.asyncio
async def test_ticketless_run_blocks_after_reassignment(sandbox_system):
    client, db, worker, _, agent = sandbox_system
    first = await engineering_task(client, db)
    second = await engineering_task(client, db)
    path = "/company/tasks/" + first["id"]
    response = await client.post(path + "/runs")
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    run = agent.db.get_run(run_id, deserialize=False)
    data = {**run["run_data"], "status": "RUNNING"}
    agent.db.upsert_run(data, session_id=run["session_id"])
    table = worker.config.db._get_table("jobs")
    with worker.config.db.Session() as session, session.begin():
        session.execute(table.delete().where(table.c.id == run_id))
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Edit work"})
    ).status_code == 200
    assert (
        await client.post(
            path + "/transitions",
            json={"target": "ready", "reason": "New executor", "executor_type": "agent", "executor_id": "writer"},
        )
    ).status_code == 200
    second_path = "/company/tasks/" + second["id"] + "/runs"
    blocked = await client.post(second_path)
    assert blocked.status_code == 409 and "live job" in blocked.text, blocked.text
    agent.db.upsert_run({**data, "status": "CANCELLED"}, session_id=run["session_id"])
    assert (await client.post(second_path)).status_code == 202


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
async def test_start_checks_permission_once_before_admission(sandbox_system, monkeypatch, authorized):
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    import agno.os.routers.company.runs as routes

    client, db, worker, _, _ = sandbox_system
    task = await engineering_task(client, db)
    permission = AsyncMock(side_effect=None if authorized else HTTPException(403, "Denied"))
    listing = AsyncMock(wraps=worker.store.list_jobs)
    monkeypatch.setattr(routes, "_require_endpoint_permission", permission)
    monkeypatch.setattr(worker.store, "list_jobs", listing)
    response = await client.post("/company/tasks/" + task["id"] + "/runs")
    assert response.status_code == (202 if authorized else 403), response.text
    permission.assert_awaited_once()
    assert listing.await_count == (1 if authorized else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_settled_retired_executor_does_not_block_admission(sandbox_system, legacy):
    from agno.db.base import AsyncBaseDb
    from tests.integration.db.test_company_execution_parity import execute

    client, db, worker, os, _ = sandbox_system
    old = await accepted(client)
    other = await engineering_task(client, db)
    path = "/company/tasks/" + old["id"]
    assert (await client.post(path + "/runs")).status_code == 202
    assert (await execute(worker))["status"] == "completed"
    assert (await client.post(path + "/transitions", json={"target": "done", "reason": "Accepted"})).status_code == 200
    old = await _call(db, "get_task", old["id"])
    table = worker.config.db._get_table("jobs")
    with worker.config.db.Session() as session, session.begin():
        session.execute(table.delete().where(table.c.id == old["job_id"]))
    if legacy:
        history = [{k: v for k, v in entry.items() if k != "run_db_id"} for entry in old["transitions"]]
        if isinstance(db, AsyncBaseDb):
            table = await db._get_table("tasks")
            async with db.db_engine.begin() as connection:
                await connection.execute(table.update().where(table.c.id == old["id"]).values(transitions=history))
        else:
            table = db._get_table("tasks")
            with db.db_engine.begin() as connection:
                connection.execute(table.update().where(table.c.id == old["id"]).values(transitions=history))
    os.dbs.pop(db.id, None)
    os.registry.agents[:] = [agent for agent in os.registry.agents if agent.id != "writer"]
    started = await client.post("/company/tasks/" + other["id"] + "/runs")
    assert started.status_code == 202, started.text


@pytest.mark.asyncio
@pytest.mark.parametrize("async_queue", [False, True])
async def test_queue_read_failure_refuses_admission(sandbox_system, monkeypatch, async_queue):
    from unittest.mock import AsyncMock

    from agno.db.postgres import AsyncPostgresDb

    client, db, worker, _, _ = sandbox_system
    task = await engineering_task(client, db)
    store = worker.config.db
    if async_queue:
        store = AsyncPostgresDb(
            db_url=str(store.db_engine.url.render_as_string(hide_password=False)), db_schema=store.db_schema
        )
        worker.store = store
    original = store._get_table

    def broken(*args, **kwargs):
        if kwargs.get("table_type") == "jobs":
            raise RuntimeError("Injected job read failure")
        return original(*args, **kwargs)

    try:
        monkeypatch.setattr(store, "_get_table", AsyncMock(side_effect=broken) if async_queue else broken)
        response = await client.post("/company/tasks/" + task["id"] + "/runs")
        assert response.status_code == 503 and "queue is unavailable" in response.text, response.text
        assert (await _call(db, "get_task", task["id"]))["status"] == "ready"
    finally:
        if async_queue:
            await store.close()


@pytest.mark.asyncio
async def test_untagged_live_job_blocks_named_deployment(sandbox_system):
    client, db, worker, _, _ = sandbox_system
    first = await engineering_task(client, db)
    second = await engineering_task(client, db)
    response = await client.post("/company/tasks/" + first["id"] + "/runs")
    assert response.status_code == 202, response.text
    worker.config.deployment_id = "new-deployment"
    job = await worker.store.claim_job(
        worker.worker_id, worker.config.lock_grace_seconds, deployment_id="new-deployment"
    )
    assert job["id"] == response.json()["run_id"] and job["deployment_id"] is None
    blocked = await client.post("/company/tasks/" + second["id"] + "/runs")
    assert blocked.status_code == 409 and "live job" in blocked.text, blocked.text


@pytest.mark.asyncio
async def test_contention_is_quiet_for_automatic_pickup(sandbox_system, system):  # noqa: F811
    from agno.company.routines import _AutomationSkip
    from tests.integration.db.test_company_execution_parity import automation

    client, db, worker, _, _ = sandbox_system
    first = await engineering_task(client, db)
    second = await engineering_task(client, db)
    assert (await client.post("/company/tasks/" + first["id"] + "/runs")).status_code == 202
    executor, _ = await automation(system)
    for _ in range(2):
        with pytest.raises(_AutomationSkip, match="still active"):
            await executor._dispatch(await _call(db, "get_task", second["id"]))
    assert (await worker.store.list_jobs())[1] == 1


@pytest.mark.asyncio
async def test_checkout_projection_error_can_retry_after_source_repair(sandbox_system):
    client, db, worker, _, agent = sandbox_system
    task = await engineering_task(client, db)
    path = "/company/tasks/" + task["id"]
    assert (await client.post(path + "/runs")).status_code == 202
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert (await client.delete("/company/sources/" + task["id"])).status_code == 204
    run = agent.db.get_run(job["id"], deserialize=False)
    data = {**run["run_data"], "status": "COMPLETED", "metadata": {"sandbox": {"repository": PIN}}}
    agent.db.upsert_run(data, session_id=run["session_id"])
    assert await worker._asettle_ticket(job["id"], job["attempt"], "completed")
    failed = await _call(db, "get_task", task["id"])
    assert failed["result"]["status"] == "ERROR"
    assert (await worker.store.get_job(job["id"]))["status"] == "completed"
    source = await client.post(
        "/company/sources", json={"product_id": task["product_id"], "type": "git", "reference": URL}
    )
    assert source.status_code == 201
    response = await client.post(path + "/runs", json={"attempt": 2})
    assert response.status_code == 202, response.text
    second = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    second_run = agent.db.get_run(second["id"], deserialize=False)
    agent.db.upsert_run(
        {**second_run["run_data"], "status": "COMPLETED", "metadata": {"sandbox": {"repository": PIN}}},
        session_id=run["session_id"],
    )
    assert await worker._asettle_ticket(second["id"], second["attempt"], "completed")
    completed = await _call(db, "get_task", task["id"])
    assert completed["status"] == "in_review" and completed["metadata"]["checkout"]["commit"] == PIN["commit"]
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Reassign"})
    ).status_code == 200
    original = agent.repository
    agent.repository = Repository("https://github.com/other/repository", "master")
    await _call(
        db,
        "create_source",
        {
            "id": "other-repo",
            "product_id": task["product_id"],
            "type": "git",
            "reference": agent.repository.url,
            "created_at": 1,
        },
    )
    refused = await client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Different repository", "executor_type": "agent", "executor_id": "engineer"},
    )
    assert refused.status_code == 409 and "already pinned" in refused.text, refused.text
    assert (await _call(db, "get_task", task["id"]))["metadata"] == completed["metadata"]
    agent.repository = original


@pytest.mark.asyncio
@pytest.mark.parametrize("first_deployment", [None, "named-deployment"])
async def test_overlapping_deployments_serialize_concurrent_starts(sandbox_system, monkeypatch, first_deployment):
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from agno.os import AgentOS, CompanyConfig
    from agno.os.job_queue import QueueWorker, resolve_queue_store

    client, db, worker, _, agent = sandbox_system
    first = await engineering_task(client, db)
    second = await engineering_task(client, db)
    worker.config.deployment_id = first_deployment
    config = QueueConfig(
        durable=True,
        db=worker.config.db,
        redis="redis://localhost:6379/0",
        max_attempts=1,
        deployment_id=None if first_deployment else "named-deployment",
    )
    replica = AgentOS(db=db, agents=[agent], company=CompanyConfig(), queue=config, telemetry=False)
    app = replica.get_app()
    replica_worker = QueueWorker(
        resolve_queue_store(config, db),
        lambda kind, id, scope=None: agent if id == agent.id else None,
        config,
        authorization_app=app,
    )
    replica_worker._company_db = db
    app.state.queue_worker = replica_worker
    scanned = asyncio.Event()
    release = asyncio.Event()
    original = worker.store.list_jobs

    async def hold_snapshot(*args, **kwargs):
        result = await original(*args, **kwargs)
        scanned.set()
        await release.wait()
        return result

    monkeypatch.setattr(worker.store, "list_jobs", hold_snapshot)
    pending = asyncio.create_task(client.post("/company/tasks/" + first["id"] + "/runs"))
    try:
        await asyncio.wait_for(scanned.wait(), 10)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://replica") as other:
            response = await asyncio.wait_for(other.post("/company/tasks/" + second["id"] + "/runs"), 10)
    finally:
        release.set()
        started = await pending
    assert started.status_code == 202, started.text
    assert response.status_code == 409, response.text
    job = await worker.store.claim_job(worker.worker_id, deployment_id="named-deployment")
    assert job["id"] == started.json()["run_id"] and job["status"] == "running"
    assert await worker.store.claim_job(worker.worker_id, deployment_id="named-deployment") is None
    assert (await _call(db, "get_task", second["id"]))["status"] == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("second_pin", ["same", "different", "missing"])
async def test_recovery_projects_and_verifies_checkout(sandbox_system, monkeypatch, second_pin):
    from unittest.mock import AsyncMock

    from agno.company.execution import _reconcile_task_run, _recover_task
    from tests.integration.db.test_company_failure_recovery import delete_ticket

    client, db, worker, os, agent = sandbox_system
    task = await engineering_task(client, db)
    path = "/company/tasks/" + task["id"] + "/runs"
    first = await client.post(path)
    assert first.status_code == 202, first.text
    reserved = await _call(db, "get_task", task["id"])
    run = agent.db.get_run(reserved["job_id"], deserialize=False)
    agent.db.upsert_run(
        {**run["run_data"], "status": "COMPLETED", "metadata": {"sandbox": {"repository": PIN}}},
        session_id=task["session_id"],
    )
    delete_ticket(worker, reserved["job_id"])
    with monkeypatch.context() as recovery:
        recovery.setattr(
            worker.store, "enqueue_job", AsyncMock(side_effect=AssertionError("Recovery must not enqueue"))
        )
        outcome = await _recover_task(os, worker, reserved)
    assert outcome["action"] == "reconciled"
    saved = await _call(db, "get_task", task["id"])
    checkout = {"source_id": task["id"], **PIN}
    assert saved["metadata"]["checkout"] == checkout
    assert saved["result"]["status"] == "COMPLETED" and saved["status"] == "in_review"
    second = await client.post(path, json={"attempt": 2})
    assert second.status_code == 202, second.text
    reserved = await _call(db, "get_task", task["id"])
    assert reserved["session_id"] == task["session_id"]
    run = agent.db.get_run(reserved["job_id"], deserialize=False)
    ticket = await worker.store.get_job(reserved["job_id"])
    assert ticket["payload"]["kwargs"]["metadata"]["repository"] == {"commit": PIN["commit"]}
    pin = {**PIN, "commit": "b" * 40} if second_pin == "different" else PIN
    data = {**run["run_data"], "status": "COMPLETED", "metadata": {"sandbox": {}}}
    if second_pin != "missing":
        data["metadata"]["sandbox"]["repository"] = pin
    agent.db.upsert_run(data, session_id=task["session_id"])
    delete_ticket(worker, reserved["job_id"])
    with monkeypatch.context() as recovery:
        recovery.setattr(
            worker.store, "enqueue_job", AsyncMock(side_effect=AssertionError("Recovery must not enqueue"))
        )
        # Repeating the HTTP start recovers the existing run rather than submitting it.
        response = await client.post(path, json={"attempt": 2})
    assert response.status_code == 202, response.text
    saved = await _call(db, "get_task", task["id"])
    assert saved["metadata"]["checkout"] == checkout
    assert saved["result"]["status"] == ("COMPLETED" if second_pin == "same" else "ERROR")
    assert saved["status"] == ("in_review" if second_pin == "same" else "in_progress")
    if second_pin != "same":
        assert "repository pin" in saved["result"]["content"]
    # A stale recovery observation cannot replace a settled result or its pin.
    agent.db.upsert_run({**data, "metadata": {"sandbox": {"repository": PIN}}}, session_id=task["session_id"])
    stale_run = agent.db.get_run(reserved["job_id"], deserialize=False)
    assert not await _reconcile_task_run(db, agent.db, reserved, stale_run, None, worker=worker)
    assert await _call(db, "get_task", task["id"]) == saved


@pytest.mark.asyncio
async def test_recovered_retry_establishes_absent_checkout(sandbox_system):
    from agno.company.execution import _recover_task
    from tests.integration.db.test_company_failure_recovery import delete_ticket

    client, db, worker, os, agent = sandbox_system
    task = await engineering_task(client, db)
    path = "/company/tasks/" + task["id"] + "/runs"
    first = await client.post(path)
    assert first.status_code == 202, first.text
    job = await worker.store.get_job(first.json()["run_id"])
    await _project_run(worker, job, "failed", "Transient first attempt")
    await worker.store.cancel_job(job["id"])
    second = await client.post(path, json={"attempt": 2})
    assert second.status_code == 202, second.text
    task = await _call(db, "get_task", task["id"])
    assert task["metadata"] is None
    run = agent.db.get_run(task["job_id"], deserialize=False)
    agent.db.upsert_run(
        {**run["run_data"], "status": "COMPLETED", "metadata": {"sandbox": {"repository": PIN}}},
        session_id=task["session_id"],
    )
    delete_ticket(worker, task["job_id"])
    assert (await _recover_task(os, worker, task))["action"] == "reconciled"
    saved = await _call(db, "get_task", task["id"])
    assert saved["metadata"]["checkout"] == {"source_id": task["id"], **PIN}
    assert saved["result"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_recovery_waits_for_missing_sandbox_executor(sandbox_system, monkeypatch):
    from unittest.mock import AsyncMock

    from agno.company.execution import _recover_task, _TaskRunUnavailable
    from tests.integration.db.test_company_failure_recovery import delete_ticket

    client, db, worker, os, agent = sandbox_system
    task = await engineering_task(client, db)
    assert (await client.post("/company/tasks/" + task["id"] + "/runs")).status_code == 202
    task = await _call(db, "get_task", task["id"])
    run = agent.db.get_run(task["job_id"], deserialize=False)
    agent.db.upsert_run(
        {**run["run_data"], "status": "COMPLETED", "metadata": {"sandbox": {"repository": PIN}}},
        session_id=task["session_id"],
    )
    delete_ticket(worker, task["job_id"])
    with monkeypatch.context() as unavailable:
        unavailable.setattr(worker, "_aresolve_job_component", AsyncMock(return_value=None))
        with pytest.raises(_TaskRunUnavailable, match="recovering its checkout"):
            await _recover_task(os, worker, task)
    assert await _call(db, "get_task", task["id"]) == task
    assert (await _recover_task(os, worker, task))["action"] == "reconciled"
    assert (await _call(db, "get_task", task["id"]))["metadata"]["checkout"] == {"source_id": task["id"], **PIN}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,executor_id", [("agent", "writer"), ("team", "editors"), ("workflow", "draft")])
@pytest.mark.parametrize("pinned", [False, True])
async def test_pinned_task_refuses_non_sandboxed_reacceptance(sandbox_system, kind, executor_id, pinned):
    from agno.company.execution import _recover_task
    from tests.integration.db.test_company_failure_recovery import delete_ticket

    client, db, worker, os, agent = sandbox_system
    task = await engineering_task(client, db)
    path = "/company/tasks/" + task["id"]
    if pinned:
        assert (await client.post(path + "/runs")).status_code == 202
        reserved = await _call(db, "get_task", task["id"])
        run = agent.db.get_run(reserved["job_id"], deserialize=False)
        agent.db.upsert_run(
            {**run["run_data"], "status": "COMPLETED", "metadata": {"sandbox": {"repository": PIN}}},
            session_id=task["session_id"],
        )
        delete_ticket(worker, reserved["job_id"])
        assert (await _recover_task(os, worker, reserved))["action"] == "reconciled"
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Reassign work"})
    ).status_code == 200
    before = await _call(db, "get_task", task["id"])
    response = await client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "New executor", "executor_type": kind, "executor_id": executor_id},
    )
    if not pinned:
        assert response.status_code == 200, response.text
        assert response.json()["executor_type"] == kind and response.json()["executor_id"] == executor_id
        return
    assert response.status_code == 409 and "requires a sandboxed executor" in response.text, response.text
    assert await _call(db, "get_task", task["id"]) == before
    # A compatible executor can still reuse the pinned session and recover a retry.
    ready = await client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Keep repository", "executor_type": "agent", "executor_id": "engineer"},
    )
    assert ready.status_code == 200, ready.text
    retry = await client.post(path + "/runs", json={"attempt": 2})
    assert retry.status_code == 202, retry.text
    reserved = await _call(db, "get_task", task["id"])
    run = agent.db.get_run(reserved["job_id"], deserialize=False)
    agent.db.upsert_run(
        {**run["run_data"], "status": "COMPLETED", "metadata": {"sandbox": {"repository": PIN}}},
        session_id=task["session_id"],
    )
    delete_ticket(worker, reserved["job_id"])
    assert (await _recover_task(os, worker, reserved))["action"] == "reconciled"
    saved = await _call(db, "get_task", task["id"])
    assert saved["session_id"] == task["session_id"]
    assert saved["metadata"] == before["metadata"]
    assert saved["result"]["status"] == "COMPLETED"
