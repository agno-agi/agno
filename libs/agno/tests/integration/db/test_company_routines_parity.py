"""Routine HTTP controls and Project-required proposals across the SQL adapters."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

from agno.company.bootstrap import arehydrate_product
from agno.company.declarations import CompanyDeclarations
from agno.company.execution import _call
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.company.routines import _manager_call
from agno.company.scheduler import CompanyScheduleExecutor
from agno.db.base import AsyncBaseDb
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID, Schedule
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


def spy_product_links(db, monkeypatch):
    calls = []
    original = type(db).add_product_routine
    if isinstance(db, AsyncBaseDb):

        async def link(self, *args, **kwargs):
            calls.append(args)
            return await original(self, *args, **kwargs)

    else:

        def link(self, *args, **kwargs):
            calls.append(args)
            return original(self, *args, **kwargs)

    monkeypatch.setattr(type(db), "add_product_routine", link)
    return calls


async def stored_state(db, routine):
    return (
        await _call(db, "get_schedule", routine["id"]),
        await _call(db, "get_schedule_runs", routine["id"]),
        await _call(db, "get_product", routine["payload"]["metadata"]["product_id"]),
    )


@pytest.mark.asyncio
async def test_enabled_on_demand_routine_refuses_pause_and_resume(system, monkeypatch):
    client, db, _, _, _ = system
    routine = await create_routine(client)
    path = "/company/routines/" + routine["id"]
    assert routine["schedule_type"] == "on_demand" and routine["enabled"]
    before = await stored_state(db, routine)
    links = spy_product_links(db, monkeypatch)
    # A later clock keeps a refused request that still wrote updated_at from hiding in the same second.
    monkeypatch.setattr(time, "time", lambda: before[0]["updated_at"] + 100)
    for _ in range(2):
        paused = await client.post(path + "/pause")
        assert paused.status_code == 409, paused.text
        assert paused.json()["detail"] == "On-demand Routines cannot be paused"
        resumed = await client.post(path + "/resume")
        assert resumed.status_code == 409, resumed.text
        assert resumed.json()["detail"] == "On-demand Routine is already enabled"
    assert links == []
    assert await stored_state(db, routine) == before


@pytest.mark.asyncio
async def test_disabled_on_demand_routine_recovers_through_resume_without_running(system, monkeypatch):
    client, db, _, _, _ = system
    routine = await create_routine(client)
    path = "/company/routines/" + routine["id"]
    await _call(db, "update_schedule", routine["id"], enabled=False)
    assert (await client.post(path + "/trigger")).status_code == 409
    disabled = await stored_state(db, routine)
    monkeypatch.setattr(time, "time", lambda: disabled[0]["updated_at"] + 100)
    for _ in range(2):
        paused = await client.post(path + "/pause")
        assert paused.status_code == 409, paused.text
        assert paused.json()["detail"] == "On-demand Routines cannot be paused"
    assert await stored_state(db, routine) == disabled
    links = spy_product_links(db, monkeypatch)
    resumed = await client.post(path + "/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["enabled"] and resumed.json()["next_run_at"] is None
    assert resumed.json()["schedule_type"] == "on_demand"
    assert len(links) == 1
    assert (await _call(db, "get_schedule_runs", routine["id"]))[1] == 0
    recovered = await stored_state(db, routine)
    monkeypatch.setattr(time, "time", lambda: recovered[0]["updated_at"] + 100)
    again = await client.post(path + "/resume")
    assert again.status_code == 409 and again.json()["detail"] == "On-demand Routine is already enabled"
    assert len(links) == 1 and await stored_state(db, routine) == recovered


@pytest.mark.asyncio
async def test_disabled_on_demand_routine_stays_disabled_when_its_product_is_archived(system):
    client, db, _, _, _ = system
    routine = await create_routine(client)
    path = "/company/routines/" + routine["id"]
    await _call(db, "update_schedule", routine["id"], enabled=False)
    product_id = routine["payload"]["metadata"]["product_id"]
    assert (await client.post("/company/products/" + product_id + "/archive")).status_code == 200
    disabled = await _call(db, "get_schedule", routine["id"])
    assert disabled["enabled"] is False
    refused = await client.post(path + "/resume")
    assert refused.status_code == 404, refused.text
    assert await _call(db, "get_schedule", routine["id"]) == disabled


@pytest.mark.asyncio
async def test_restored_on_demand_routine_is_enabled_then_triggers(system):
    client, db, worker, _, _ = system
    routine = await create_routine(client)
    path = "/company/routines/" + routine["id"]
    assert (await client.post(path + "/archive")).status_code == 200
    for action in ("trigger", "pause", "resume"):
        assert (await client.post(path + "/" + action)).status_code == 404, action
    restored = await client.post(path + "/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["enabled"] and restored.json()["deleted_at"] is None
    assert restored.json()["next_run_at"] is None
    assert (await client.post(path + "/pause")).status_code == 409
    assert (await client.post(path + "/resume")).status_code == 409
    assert (await _call(db, "get_schedule_runs", routine["id"]))[1] == 0
    worker.authorization_app.state.scheduler_executor = await routine_executor(system)
    started = await client.post(path + "/trigger")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "success", started.text
    assert (await _call(db, "get_schedule_runs", routine["id"]))[1] == 1


@pytest.mark.asyncio
async def test_archived_routines_are_filtered_before_sorting_and_paging(system):
    client, db, _, _, _ = system
    product_id = await seed_routines(client, db, {"r-a": (100, 500), "r-b": (200, 300), "r-c": (300, 400)})
    assert (await client.post("/company/routines/r-b/archive")).status_code == 200
    params = {"product_id": product_id, "sort_by": "updated_at", "sort_order": "asc"}
    assert await listed_ids(client, **params) == (["r-c", "r-a"], 2)
    everything = await listed_ids(client, include_deleted=True, **params)
    assert sorted(everything[0]) == ["r-a", "r-b", "r-c"] and everything[1] == 3


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
    assert (await client.post(path + "/resume")).status_code == 409
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
    approval = {"target": "active", "reason": "Approved"}
    await client.post("/company/projects/" + project["id"] + "/transitions", json=approval)
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


@pytest.fixture
def clock(monkeypatch):
    """A time.time the test advances itself, so no two writes share a second."""
    now = [int(time.time())]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now


async def company_executor(system):
    _, db, _, _, _ = system
    plain = await routine_executor(system)
    executor = CompanyScheduleExecutor(
        company_db=db,
        schedule_db=db,
        base_url="http://test",
        internal_service_token="contract-internal",
        poll_interval=0,
    )
    executor._get_client = plain._get_client
    return executor


async def claim_routine(db, routine_id):
    # The setup write stamps updated_at; tests read the stored value after it.
    await _call(db, "update_schedule", routine_id, next_run_at=1)
    claimed = await _call(db, "claim_due_schedule", "worker")
    assert claimed["id"] == routine_id
    return claimed


async def stored_updated_at(db, routine_id):
    return (await _call(db, "get_schedule", routine_id))["updated_at"]


@pytest.mark.asyncio
async def test_user_edits_advance_routine_updated_at(system, clock):
    client, db, _, _, _ = system
    routine = await create_routine(client, cron_expr="0 * * * *")
    path = "/company/routines/" + routine["id"]
    edits = [
        ("PATCH", "", {"name": "renamed"}),
        ("PATCH", "", {"instructions": "Review again"}),
        ("PATCH", "", {"cron_expr": "30 * * * *", "timezone": "Asia/Kolkata"}),
        ("PATCH", "", {"executor_type": "team", "executor_id": "editors"}),
        ("POST", "/pause", None),
        ("POST", "/resume", None),
    ]
    for method, suffix, body in edits:
        clock[0] += 100
        response = await client.request(method, path + suffix, json=body)
        assert response.status_code == 200, response.text
        assert await stored_updated_at(db, routine["id"]) == clock[0], (method, suffix, body)


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["scheduled", "manual"])
async def test_execution_leaves_routine_updated_at(system, clock, trigger):
    client, db, worker, _, _ = system
    routine = await create_routine(client, cron_expr="0 * * * *")
    path = "/company/routines/" + routine["id"]
    executor = await company_executor(system)
    worker.authorization_app.state.scheduler_executor = executor
    for _ in range(2):
        clock[0] += 1000
        claimed = await claim_routine(db, routine["id"]) if trigger == "scheduled" else None
        edited = await stored_updated_at(db, routine["id"])
        clock[0] += 1000
        if claimed:
            assert (await executor.execute(claimed, db))["status"] == "success"
        else:
            assert (await client.post(path + "/trigger")).status_code == 200
        saved = await _call(db, "get_schedule", routine["id"])
        assert saved["updated_at"] == edited
        assert saved["locked_by"] is None
        if claimed:
            assert saved["next_run_at"] not in (None, 1)
        assert (await client.get(path)).json()["last_run"]["status"] == "success"


@pytest.mark.asyncio
async def test_user_edit_during_run_survives_release(system, clock):
    client, db, _, _, _ = system
    routine = await create_routine(client, cron_expr="0 * * * *")
    claimed = await claim_routine(db, routine["id"])
    clock[0] += 500
    edited = await client.patch("/company/routines/" + routine["id"], json={"name": "edited mid-run"})
    assert edited.status_code == 200, edited.text
    edit_time = clock[0]
    clock[0] += 500
    # A release from another worker is fenced out and writes nothing.
    assert not await _call(
        db, "release_schedule", routine["id"], next_run_at=1, worker_id="other", locked_at=claimed["locked_at"]
    )
    assert await stored_updated_at(db, routine["id"]) == edit_time
    # The run finishes with the claim-time snapshot and releases the lock.
    assert (await (await company_executor(system)).execute(claimed, db))["status"] == "success"
    saved = await _call(db, "get_schedule", routine["id"])
    assert saved["locked_by"] is None and saved["updated_at"] == edit_time
    assert saved["name"].endswith("edited mid-run")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cause,reason",
    [
        ("endpoint_drift", "endpoint_drift:/agents/other/runs!=agent:writer"),
        ("invalid_cron", None),
        ("archived_product", "company_product_archived"),
    ],
)
async def test_automatic_disable_leaves_routine_updated_at(system, clock, cause, reason):
    client, db, _, _, _ = system
    routine = await create_routine(client, cron_expr="0 * * * *")
    if cause == "endpoint_drift":
        await _call(db, "update_schedule", routine["id"], endpoint="/agents/other/runs")
    elif cause == "invalid_cron":
        await _call(db, "update_schedule", routine["id"], cron_expr="not a cron")
    else:
        product_id = (await _call(db, "get_schedule", routine["id"]))["payload"]["metadata"]["product_id"]
        assert (await client.post("/company/products/" + product_id + "/archive")).status_code == 200
    claimed = await claim_routine(db, routine["id"])
    edited = await stored_updated_at(db, routine["id"])
    clock[0] += 1000
    await (await company_executor(system)).execute(claimed, db)
    saved = await _call(db, "get_schedule", routine["id"])
    assert saved["enabled"] is False and saved["disabled_reason"] == reason
    assert saved["locked_by"] is None
    assert saved["updated_at"] == edited


@pytest.mark.asyncio
async def test_target_archive_cascade_leaves_routine_updated_at(system, clock):
    client, db, _, _, _ = system
    routine = await create_routine(client)
    ordinary = await ScheduleManager(db).acreate(name="ordinary", cron="0 * * * *", endpoint="/agents/writer/runs")
    legacy = Schedule(
        id="legacy",
        name="legacy",
        cron_expr="",
        endpoint="/agents/writer/runs",
        managed_by="company",
        target_type="agent",
        target_id="writer",
    )
    await _call(db, "create_schedule", legacy.to_dict())
    edited = await stored_updated_at(db, routine["id"])
    clock[0] += 1000
    reason = "target_archived:agent:writer"
    assert await _call(db, "disable_schedules_for_target", "agent", "writer", reason=reason) == 3
    saved = await _call(db, "get_schedule", routine["id"])
    assert saved["enabled"] is False and saved["disabled_reason"] == reason
    assert saved["updated_at"] == edited
    assert await stored_updated_at(db, "legacy") is None
    assert await stored_updated_at(db, ordinary.id) == clock[0]


@pytest.mark.asyncio
async def test_release_and_update_still_stamp_ordinary_schedules(system, clock):
    _, db, _, _, _ = system
    ordinary = await ScheduleManager(db).acreate(name="ordinary", cron="0 * * * *", endpoint="/agents/writer/runs")
    await _call(db, "update_schedule", ordinary.id, next_run_at=1)
    claimed = await _call(db, "claim_due_schedule", "worker")
    assert claimed["id"] == ordinary.id
    clock[0] += 1000
    assert await _call(
        db, "release_schedule", ordinary.id, next_run_at=2, worker_id="worker", locked_at=claimed["locked_at"]
    )
    assert await stored_updated_at(db, ordinary.id) == clock[0]
    clock[0] += 1000
    await _call(db, "update_schedule", ordinary.id, enabled=False)
    assert await stored_updated_at(db, ordinary.id) == clock[0]


async def seed_routines(client, db, rows):
    """Store routines of one Product with fixed timestamps, as {id: (created_at, updated_at)} or {id: fields}."""
    template = await create_routine(client)
    stored = await _call(db, "get_schedule", template["id"])
    product_id = stored["payload"]["metadata"]["product_id"]
    assert await _call(db, "delete_schedule", template["id"])
    for routine_id, fields in rows.items():
        if isinstance(fields, tuple):
            fields = {"created_at": fields[0], "updated_at": fields[1]}
        name = product_id + "." + routine_id
        await _call(db, "create_schedule", {**stored, "id": routine_id, "name": name, **fields})
    return product_id


async def listed_ids(client, **params):
    """Walk every page of one item and return (ids, total_count)."""
    ids, page = [], 1
    while True:
        response = await client.get("/company/routines", params={**params, "limit": 1, "page": page})
        assert response.status_code == 200, response.text
        body = response.json()
        ids += [row["id"] for row in body["data"]]
        if page >= body["meta"]["total_pages"]:
            return ids, body["meta"]["total_count"]
        page += 1


@pytest.mark.asyncio
async def test_routine_sorting_precedes_paging(system):
    client, db, _, _, _ = system
    # Creation order differs from update order; one NULL updated_at; two pairs of equal timestamps.
    product_id = await seed_routines(
        client,
        db,
        {
            "r-a": (100, 500),
            "r-b": (200, 300),
            "r-c": (300, None),
            "r-d": (400, 400),
            "r-e": (400, 400),
        },
    )
    other = await create_routine(client)
    ordinary = await ScheduleManager(db).acreate(name="ordinary", cron="0 * * * *", endpoint="/agents/writer/runs")
    expected = {
        ("created_at", "desc"): ["r-e", "r-d", "r-c", "r-b", "r-a"],
        ("created_at", "asc"): ["r-a", "r-b", "r-c", "r-d", "r-e"],
        ("updated_at", "desc"): ["r-a", "r-e", "r-d", "r-c", "r-b"],
        ("updated_at", "asc"): ["r-b", "r-c", "r-d", "r-e", "r-a"],
    }
    for (sort_by, sort_order), ids in expected.items():
        found = await listed_ids(client, product_id=product_id, sort_by=sort_by, sort_order=sort_order)
        assert found == (ids, 5), (sort_by, sort_order)
    # A single parameter takes the other one's default.
    assert await listed_ids(client, product_id=product_id) == (expected[("created_at", "desc")], 5)
    updated = await listed_ids(client, product_id=product_id, sort_by="updated_at")
    assert updated == (expected[("updated_at", "desc")], 5)
    assert await listed_ids(client, product_id=product_id, sort_order="asc") == (expected[("created_at", "asc")], 5)
    # Filtering happens before counting; ordinary schedules never appear.
    everything, total = await listed_ids(client, sort_by="created_at", sort_order="asc")
    assert total == 6 and everything[:5] == expected[("created_at", "asc")] and everything[5] == other["id"]
    assert ordinary.id not in everything
    assert await listed_ids(client, product_id=other["payload"]["metadata"]["product_id"]) == ([other["id"]], 1)
    for bad in ({"sort_by": "name"}, {"sort_order": "sideways"}):
        assert (await client.get("/company/routines", params=bad)).status_code == 422


@pytest.mark.asyncio
async def test_routine_sorting_by_next_run_schedule_type_and_enabled(system):
    client, db, _, _, _ = system
    hourly = "0 * * * *"
    # Creation order differs from id order, so ties show which one breaks them.
    product_id = await seed_routines(
        client,
        db,
        {
            "r-a": {"created_at": 500, "cron_expr": hourly, "enabled": True, "next_run_at": 1000},
            "r-b": {"created_at": 200, "cron_expr": hourly, "enabled": True, "next_run_at": 1000},
            # Paused: its stored next run doesn't count.
            "r-c": {"created_at": 400, "cron_expr": hourly, "enabled": False, "next_run_at": 500},
            "r-d": {"created_at": 300, "cron_expr": "", "enabled": True, "next_run_at": None},
            "r-e": {"created_at": 100, "cron_expr": hourly, "enabled": True, "next_run_at": 2000},
        },
    )
    expected = {
        # Routines without a next run come last in both directions.
        ("next_run_at", "asc"): ["r-b", "r-a", "r-e", "r-d", "r-c"],
        ("next_run_at", "desc"): ["r-e", "r-a", "r-b", "r-c", "r-d"],
        # Ties fall back to creation time in the same direction.
        ("schedule_type", "asc"): ["r-d", "r-e", "r-b", "r-c", "r-a"],
        ("schedule_type", "desc"): ["r-a", "r-c", "r-b", "r-e", "r-d"],
        ("enabled", "asc"): ["r-c", "r-e", "r-b", "r-d", "r-a"],
        ("enabled", "desc"): ["r-a", "r-d", "r-b", "r-e", "r-c"],
    }
    for (sort_by, sort_order), ids in expected.items():
        found = await listed_ids(client, product_id=product_id, sort_by=sort_by, sort_order=sort_order)
        assert found == (ids, 5), (sort_by, sort_order)


@pytest.mark.asyncio
async def test_execution_keeps_routine_order_and_edit_changes_it(system, clock):
    client, db, _, _, _ = system
    older = await create_routine(client, cron_expr="0 * * * *")
    clock[0] += 100
    newer = await create_routine(client, cron_expr="0 * * * *")

    async def order(sort_by):
        response = await client.get("/company/routines", params={"sort_by": sort_by})
        return [row["id"] for row in response.json()["data"]]

    clock[0] += 100
    claimed = await claim_routine(db, older["id"])
    clock[0] += 100
    assert (await client.patch("/company/routines/" + newer["id"], json={"name": "edited"})).status_code == 200
    assert await order("updated_at") == [newer["id"], older["id"]]
    # Running the older routine must not lift it above the one edited before the run.
    clock[0] += 1000
    assert (await (await routine_executor(system)).execute(claimed, db))["status"] == "success"
    assert await order("updated_at") == [newer["id"], older["id"]]
    clock[0] += 1000
    assert (await client.patch("/company/routines/" + older["id"], json={"name": "edited"})).status_code == 200
    assert await order("updated_at") == [older["id"], newer["id"]]
    assert await order("created_at") == [newer["id"], older["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["delete", "create"])
@pytest.mark.parametrize("repeat", range(2))
async def test_routine_creation_does_not_orphan_schedule_during_product_purge(system, monkeypatch, winner, repeat):
    client, db, _, _, _ = system
    await _call(db, "_create_all_tables")
    product = (await client.post("/company/products", json={"name": "Concurrent routine"})).json()
    catalog_read, release_delete = asyncio.Event(), asyncio.Event()
    schedule_saved, release_create = asyncio.Event(), asyncio.Event()
    original_list = ScheduleManager.alist_all
    original_create = db.create_schedule

    async def held_list(self, *args, **kwargs):
        rows = await original_list(self, *args, **kwargs)
        catalog_read.set()
        await asyncio.wait_for(release_delete.wait(), 10)
        return rows

    async def held_create(*args, **kwargs):
        row = (
            await original_create(*args, **kwargs)
            if isinstance(db, AsyncBaseDb)
            else await asyncio.to_thread(original_create, *args, **kwargs)
        )
        schedule_saved.set()
        await asyncio.wait_for(release_create.wait(), 10)
        return row

    monkeypatch.setattr(ScheduleManager, "alist_all", held_list)
    monkeypatch.setattr(db, "create_schedule", held_create)
    deletion = asyncio.create_task(client.delete("/company/products/" + product["id"]))
    creation = None
    try:
        await asyncio.wait_for(catalog_read.wait(), 10)
        creation = asyncio.create_task(
            client.post(
                "/company/routines",
                json={
                    "product_id": product["id"],
                    "name": "Concurrent",
                    "instructions": "Review",
                    "executor_type": "agent",
                    "executor_id": "writer",
                },
            )
        )
        await asyncio.wait_for(schedule_saved.wait(), 10)
        if winner == "delete":
            release_delete.set()
            assert (await asyncio.wait_for(deletion, 10)).status_code == 204
            release_create.set()
            assert (await asyncio.wait_for(creation, 10)).status_code == 422
        else:
            release_create.set()
            assert (await asyncio.wait_for(creation, 10)).status_code == 201
            release_delete.set()
            assert (await asyncio.wait_for(deletion, 10)).status_code == 409
    finally:
        release_delete.set()
        release_create.set()
        await asyncio.gather(deletion, *([creation] if creation else []), return_exceptions=True)
    schedules = await original_list(ScheduleManager(db))
    owned = [row for row in schedules if (row.payload or {}).get("metadata", {}).get("product_id") == product["id"]]
    assert len(owned) == (1 if winner == "create" else 0)
    assert (await _call(db, "get_product", product["id"]) is not None) == (winner == "create")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "false"])
async def test_routine_link_cleanup_failure_is_not_hidden(system, monkeypatch, failure):
    client, db, _, _, _ = system
    product = (await client.post("/company/products", json={"name": "Failed compensation"})).json()

    async def refuse_link(*args, **kwargs):
        await _call(db, "purge_product", product["id"], verified_routine_ids=())
        raise ValueError("Product disappeared")

    async def refuse_cleanup(*args, **kwargs):
        if failure == "raises":
            raise RuntimeError("Schedule cleanup unavailable")
        return False

    monkeypatch.setattr(db, "add_product_routine", refuse_link)
    monkeypatch.setattr(ScheduleManager, "adelete", refuse_cleanup)
    fields = {
        "product_id": product["id"],
        "name": "Unlinked",
        "instructions": "Review",
        "executor_type": "agent",
        "executor_id": "writer",
    }
    if failure == "raises":
        with pytest.raises(RuntimeError, match="Schedule cleanup unavailable") as error:
            await client.post("/company/routines", json=fields)
        assert error.value.__context__ is not None
    else:
        failed = await client.post("/company/routines", json=fields)
        assert failed.status_code == 503
        assert "cleanup" in failed.text
    owned = [
        row
        for row in await ScheduleManager(db).alist_all()
        if (row.payload or {}).get("metadata", {}).get("product_id") == product["id"]
    ]
    assert len(owned) == 1 and not owned[0].enabled
