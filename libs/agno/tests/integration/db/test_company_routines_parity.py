"""Routine HTTP controls and Project-required proposals across the SQL adapters."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

from agno.company.bootstrap import arehydrate_product
from agno.company.declarations import CompanyDeclarations
from agno.company.execution import _call
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import _manager_call
from agno.db.base import AsyncBaseDb
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID
from agno.scheduler import ScheduleManager
from agno.scheduler.poller import SchedulePoller
from agno.tools.company import CompanyTools
from tests.integration.db.test_company_execution_parity import routine_executor
from tests.integration.db.test_company_execution_parity import system as execution_system

system = execution_system


async def create_routine(client, **fields):
    product = (await client.post("/company/products", json={"name": "Routine controls"})).json()
    response = await client.post(
        "/company/routines",
        json=dict(
            product_id=product["id"],
            name="scan",
            instructions="Review changes",
            executor_type="agent",
            executor_id="writer",
            **fields,
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_trigger_read_pause_and_latest_run(system):
    client, db, worker, _, _ = system
    routine = await create_routine(client, cron_expr="0 * * * *")
    path = "/company/routines/" + routine["id"]
    assert routine["last_run"] is None and routine["schedule_type"] == "scheduled"
    assert (await client.get(path)).json() == routine
    assert (await client.get("/company/routines")).json()["data"] == [routine]
    worker.authorization_app.state.scheduler_executor = await routine_executor(system)
    started = await client.post(path + "/trigger")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "success", started.text
    last = (await client.get(path)).json()["last_run"]
    assert set(last) == {"status", "triggered_at", "completed_at", "run_id", "session_id", "error"}
    assert last["run_id"] == started.json()["run_id"] and last["session_id"]
    assert last["status"] == "success" and last["completed_at"] >= last["triggered_at"]
    assert last["error"] is None
    assert (await client.post(path + "/pause")).json()["last_run"] == last
    assert (await client.post(path + "/trigger")).status_code == 409
    assert (await client.post(path + "/resume")).json()["enabled"]
    ordinary = await ScheduleManager(db).acreate(name="ordinary", cron="0 * * * *", endpoint="/agents/writer/runs")
    for hidden in (COMPANY_AUTOMATION_SCHEDULE_ID, ordinary.id):
        assert (await client.get("/company/routines/" + hidden)).status_code == 404
        assert (await client.post("/company/routines/" + hidden + "/trigger")).status_code == 404


@pytest.mark.asyncio
async def test_last_run_is_one_query_per_page(system):
    client, db, _, _, _ = system
    routines = [await create_routine(client) for _ in range(5)]
    for index, routine in enumerate(routines):
        for stamp in (10, 20):
            await _call(
                db,
                "create_schedule_run",
                dict(
                    id=f"run-{index}-{stamp}",
                    schedule_id=routine["id"],
                    status="success",
                    attempt=1,
                    triggered_at=stamp,
                    created_at=stamp,
                    run_id=f"execution-{stamp}",
                ),
            )
    engine = db.db_engine.sync_engine if isinstance(db, AsyncBaseDb) else db.db_engine
    queries = []

    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "schedule_runs" in statement:
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        for limit in (1, 5):
            queries.clear()
            response = await client.get("/company/routines", params={"limit": limit})
            assert response.status_code == 200, response.text
            assert len(response.json()["data"]) == limit
            assert all(row["last_run"]["run_id"] == "execution-20" for row in response.json()["data"])
            assert len(queries) == 1, queries
    finally:
        event.remove(engine, "before_cursor_execute", count)


@pytest.mark.asyncio
async def test_on_demand_never_polled_restart_and_cron_changes(system):
    client, db, worker, os, _ = system
    # YAML and code startup use the same validated declarations and stable ids.
    declaration = CompanyDeclarations.model_validate(
        {
            "products": [
                {
                    "name": "Declared",
                    "routines": [
                        {"name": "manual", "template": "summary", "executor_type": "agent", "executor_id": "writer"}
                    ],
                }
            ]
        }
    ).products[0]
    product = await arehydrate_product(db, declaration, os.registry)
    rows = (await client.get("/company/routines", params={"product_id": product["id"]})).json()["data"]
    assert len(rows) == 1
    routine = rows[0]
    assert routine["enabled"] and routine["cron_expr"] is None and routine["next_run_at"] is None
    assert routine["schedule_type"] == "on_demand"
    executor = AsyncMock()
    reopened = type(db).from_dict(db.to_dict())
    try:
        for storage in (db, reopened):
            await arehydrate_product(storage, declaration, os.registry)
            poller = SchedulePoller(storage, executor)
            poller._running = True
            await poller._poll_once()
            await poller._poll_once()
            assert not poller._in_flight
            executor.execute.assert_not_called()
    finally:
        await _call(reopened, "close")
    path = "/company/routines/" + routine["id"]
    worker.authorization_app.state.scheduler_executor = await routine_executor(system)
    triggered = await client.post(path + "/trigger")
    assert triggered.status_code == 200 and triggered.json()["status"] == "success", triggered.text
    history = (await client.get(path + "/runs")).json()["data"]
    assert len(history) == 1
    recurring = await client.patch(path, json={"cron_expr": "0 * * * *"})
    assert recurring.status_code == 200, recurring.text
    assert recurring.json()["next_run_at"] is not None and recurring.json()["schedule_type"] == "scheduled"
    assert (await client.patch(path, json={"cron_expr": ""})).status_code == 422
    assert (await client.post(path + "/pause")).status_code == 200
    manual = await client.patch(path, json={"cron_expr": None})
    assert manual.status_code == 200, manual.text
    assert manual.json()["next_run_at"] is None and manual.json()["schedule_type"] == "on_demand"
    assert (await client.post(path + "/trigger")).status_code == 409
    resumed = (await client.post(path + "/resume")).json()
    assert resumed["enabled"] and resumed["next_run_at"] is None
    assert (await client.get(path + "/runs")).json()["data"] == history
    await arehydrate_product(db, declaration, os.registry)
    assert (await client.get(path)).json()["next_run_at"] is None


@pytest.mark.asyncio
async def test_task_and_intake_require_project(system):
    client, db, _, os, _ = system
    product = (await client.post("/company/products", json={"name": "Project required"})).json()
    for missing in ({}, {"project_id": None}, {"project_id": ""}):
        refused = await client.post("/company/tasks", json={"product_id": product["id"], "title": "Work", **missing})
        assert refused.status_code == 422, refused.text
    manager = AsyncCompanyManager(db, os.registry) if isinstance(db, AsyncBaseDb) else CompanyManager(db, os.registry)
    with pytest.raises(ValueError, match="requires a Project"):
        await _manager_call(manager, "create_task", product_id=product["id"], title="Work")
    with pytest.raises(ValueError, match="requires a Project"):
        await _manager_call(manager, "intake", source_id="source", run_id="run", proposal={})
    tools = CompanyTools(db)
    for async_tools in (False, True):
        if not async_tools and isinstance(db, AsyncBaseDb):
            continue
        prefix = "a" if async_tools else ""
        for name, args in (
            ("propose_company_task", (product["id"], "Work")),
            ("intake_product_source", ("source", "Work", "Brief", "key", ["link"], {"link": "hash"})),
        ):
            with pytest.raises(ValueError, match="requires a Project"):
                result = getattr(tools, prefix + name)(*args)
                if asyncio.iscoroutine(result):
                    await result
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Release"})).json()
    task = await client.post(
        "/company/tasks", json={"product_id": product["id"], "project_id": project["id"], "title": "Work"}
    )
    assert task.status_code == 201, task.text
    assert (await client.patch("/company/tasks/" + task.json()["id"], json={"project_id": None})).status_code == 422


@pytest.mark.asyncio
async def test_running_routine_exposes_cancel_id_before_completion(system):
    from agno.scheduler.executor import ScheduleExecutor
    from tests.integration.db.test_company_execution_parity import SimpleClient, execute

    client, db, worker, _, _ = system
    routine = await create_routine(client)
    app = worker.authorization_app
    app.state.internal_service_token = "contract-internal"
    executor = ScheduleExecutor(base_url="http://test", internal_service_token="contract-internal", poll_interval=0)
    executor._get_client = AsyncMock(return_value=SimpleClient(client.request))
    polling = asyncio.Event()
    finish = asyncio.Event()
    original = executor._poll_run

    async def hold_poll(*args):
        polling.set()
        await finish.wait()
        return await original(*args)

    executor._poll_run = hold_poll
    app.state.scheduler_executor = executor
    path = "/company/routines/" + routine["id"]
    trigger = asyncio.create_task(client.post(path + "/trigger"))
    try:
        await asyncio.wait_for(polling.wait(), 10)
        live = (await client.get(path)).json()["last_run"]
        assert live["status"] == "running" and live["completed_at"] is None
        assert live["run_id"] and live["session_id"]
        cancel = await client.post(f"/agents/writer/runs/{live['run_id']}/cancel")
        assert cancel.status_code == 200, cancel.text
        # The existing queue cancellation path owns the run's terminal state.
        job = await worker.store.get_job(live["run_id"])
        if job["status"] == "pending":
            await execute(worker)
        finish.set()
        result = await asyncio.wait_for(trigger, 10)
        assert result.status_code == 200, result.text
        assert result.json()["run_id"] == live["run_id"]
        final = (await client.get(path)).json()["last_run"]
        assert final["run_id"] == live["run_id"] and final["completed_at"] is not None
    finally:
        finish.set()
        if not trigger.done():
            trigger.cancel()
        await asyncio.gather(trigger, return_exceptions=True)


@pytest.mark.asyncio
async def test_clearing_cron_during_claim_cannot_rearm_routine(system):
    client, db, _, _, _ = system
    routine = await create_routine(client, cron_expr="0 * * * *")
    await _call(db, "update_schedule", routine["id"], next_run_at=1)
    claimed = await _call(db, "claim_due_schedule", "worker")
    assert claimed["id"] == routine["id"]
    path = "/company/routines/" + routine["id"]
    cleared = await client.patch(path, json={"cron_expr": None})
    assert cleared.status_code == 200, cleared.text
    assert await _call(
        db, "release_schedule", routine["id"], next_run_at=1, worker_id="worker", locked_at=claimed["locked_at"]
    )
    saved = await _call(db, "get_schedule", routine["id"])
    assert saved["enabled"] and saved["next_run_at"] is None and saved["locked_by"] is None
    assert await _call(db, "claim_due_schedule", "worker") is None
