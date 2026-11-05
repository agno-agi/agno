"""Generic on-demand schedules across synchronous and asynchronous SQL adapters."""

from unittest.mock import AsyncMock

import pytest

from agno.company.execution import _call
from agno.db.base import AsyncBaseDb
from agno.scheduler import ScheduleManager, SchedulePoller
from tests.integration.db.test_company_execution_parity import routine_executor
from tests.integration.db.test_company_execution_parity import system as execution_system

system = execution_system


@pytest.mark.asyncio
@pytest.mark.parametrize("cron_fields", [{}, {"cron_expr": ""}], ids=["omitted", "empty"])
async def test_plain_on_demand_poll_restart_trigger_and_cron(system, cron_fields):
    client, db, worker, _, _ = system
    response = await client.post(
        "/schedules",
        json={
            "name": "manual",
            "endpoint": "/agents/writer/runs",
            "payload": {"message": "Review changes"},
            **cron_fields,
        },
    )
    assert response.status_code == 201, response.text
    schedule = response.json()
    path = "/schedules/" + schedule["id"]
    assert schedule["managed_by"] is None
    assert schedule["cron_expr"] is None and schedule["enabled"] and schedule["next_run_at"] is None
    stored = await _call(db, "get_schedule", schedule["id"])
    assert stored["cron_expr"] == ""
    reopened = type(db).from_dict(db.to_dict())
    executor = AsyncMock()
    try:
        for storage in (db, reopened):
            poller = SchedulePoller(storage, executor)
            poller._running = True
            await poller._poll_once()
            await poller._poll_once()
            assert not poller._in_flight
            executor.execute.assert_not_called()
    finally:
        await _call(reopened, "close")
    worker.authorization_app.state.scheduler_executor = await routine_executor(system)
    started = await client.post(path + "/trigger")
    assert started.status_code == 200 and started.json()["status"] == "success", started.text
    history = (await client.get(path + "/runs")).json()["data"]
    assert len(history) == 1
    assert history[0]["run_id"] == started.json()["run_id"]
    assert (await client.get(path)).json()["next_run_at"] is None
    recurring = await client.patch(path, json={"cron_expr": "0 * * * *"})
    assert recurring.status_code == 200 and recurring.json()["next_run_at"] is not None, recurring.text
    # Clearing a cron while claimed must also defeat release from the older snapshot.
    await _call(db, "update_schedule", schedule["id"], next_run_at=1)
    claimed = await _call(db, "claim_due_schedule", "worker")
    assert claimed["id"] == schedule["id"]
    cleared = await client.patch(path, json={"cron_expr": ""})
    assert cleared.status_code == 200 and cleared.json()["next_run_at"] is None, cleared.text
    assert await _call(
        db, "release_schedule", schedule["id"], next_run_at=1, worker_id="worker", locked_at=claimed["locked_at"]
    )
    assert await _call(db, "claim_due_schedule", "worker") is None
    assert (await client.post(path + "/disable")).status_code == 200
    enabled = await client.post(path + "/enable")
    assert enabled.status_code == 200 and enabled.json()["next_run_at"] is None, enabled.text
    assert (await client.get(path + "/runs")).json()["data"] == history


@pytest.mark.asyncio
async def test_python_on_demand_create_upsert_and_enable(system):
    _, db, _, _, _ = system
    manager = ScheduleManager(db)
    for asynchronous in [True] if isinstance(db, AsyncBaseDb) else [False, True]:

        async def call(method, /, *args, **kwargs):
            if asynchronous:
                return await getattr(manager, "a" + method)(*args, **kwargs)
            return getattr(manager, method)(*args, **kwargs)

        name = "manual-python-" + str(asynchronous)
        schedule = await call("create", name=name, cron="", endpoint="/agents/writer/runs")
        assert schedule.enabled and schedule.next_run_at is None
        await call("disable", schedule.id)
        enabled = await call("enable", schedule.id)
        assert enabled.enabled and enabled.next_run_at is None
        recurring = await call(
            "create", name=name, cron="0 * * * *", endpoint="/agents/writer/runs", if_exists="update"
        )
        assert recurring.next_run_at is not None
        manual = await call("create", name=name, cron="", endpoint="/agents/writer/runs", if_exists="update")
        assert manual.id == schedule.id and manual.next_run_at is None


@pytest.mark.asyncio
async def test_python_cron_updates_replace_deadline(system):
    _, db, _, _, _ = system
    manager = ScheduleManager(db)
    for asynchronous in [True] if isinstance(db, AsyncBaseDb) else [False, True]:

        async def call(method, /, *args, **kwargs):
            if asynchronous:
                return await getattr(manager, "a" + method)(*args, **kwargs)
            return getattr(manager, method)(*args, **kwargs)

        schedule = await call(
            "create", name="cron-update-" + str(asynchronous), cron="", endpoint="/agents/writer/runs"
        )
        recurring = await call("update", schedule.id, cron_expr="0 9 * * *")
        assert recurring.next_run_at is not None
        # A timezone edit must also replace a deadline derived from the old timezone.
        await _call(db, "update_schedule", schedule.id, next_run_at=1)
        moved = await call("update", schedule.id, timezone="America/New_York")
        assert moved.timezone == "America/New_York" and moved.next_run_at > 1
        before = await _call(db, "get_schedule", schedule.id)
        for invalid in ({"cron_expr": "bad cron"}, {"cron_expr": None}, {"timezone": "bad/timezone"}):
            with pytest.raises(ValueError):
                await call("update", schedule.id, **invalid)
            assert await _call(db, "get_schedule", schedule.id) == before
        await _call(db, "update_schedule", schedule.id, next_run_at=1)
        manual = await call("update", schedule.id, cron_expr="")
        assert manual.next_run_at is None and manual.enabled
        assert await _call(db, "claim_due_schedule", "worker") is None
        await call("disable", schedule.id)
        paused = await call("update", schedule.id, cron_expr="0 9 * * *")
        assert not paused.enabled and paused.next_run_at is None
        enabled = await call("enable", schedule.id)
        assert enabled.enabled and enabled.next_run_at is not None
        await call("disable", schedule.id)
        enabled = await call("update", schedule.id, enabled=True, cron_expr="0 12 * * *")
        assert enabled.enabled and enabled.next_run_at is not None
        await call("delete", schedule.id)
