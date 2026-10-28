"""Release fencing and on-demand cadence edits against real MongoDB."""

import os
import time
from uuid import uuid4

import pytest

from agno.company.execution import _call
from agno.db.mongo import AsyncMongoDb, MongoDb
from agno.db.schemas.scheduler import Schedule
from agno.scheduler import ScheduleManager


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("next_run_at", [None, 1])
async def test_mongo_release_preserves_on_demand_and_claim_fence(asynchronous, next_run_at):
    url = os.getenv("AGNO_TEST_MONGO_URL")
    if not url:
        pytest.skip("AGNO_TEST_MONGO_URL is required")
    cls = AsyncMongoDb if asynchronous else MongoDb
    db = cls(db_url=url, db_name="scheduler_release_" + uuid4().hex)
    try:
        manager = ScheduleManager(db)
        schedule = await manager.acreate(name="release", cron="* * * * *", endpoint="/agents/writer/runs")
        await _call(db, "update_schedule", schedule.id, next_run_at=1)
        claimed = await _call(db, "claim_due_schedule", "worker")
        assert claimed is not None
        await manager.aupdate(schedule.id, cron_expr="")
        assert not await _call(
            db,
            "release_schedule",
            schedule.id,
            next_run_at=next_run_at,
            worker_id="other",
            locked_at=claimed["locked_at"],
        )
        assert (await _call(db, "get_schedule", schedule.id))["locked_by"] == "worker"
        assert await _call(
            db,
            "release_schedule",
            schedule.id,
            next_run_at=next_run_at,
            worker_id="worker",
            locked_at=claimed["locked_at"],
        )
        saved = await _call(db, "get_schedule", schedule.id)
        assert saved["next_run_at"] is None and saved["locked_by"] is None
        assert await _call(db, "claim_due_schedule", "worker") is None
        await manager.aupdate(schedule.id, cron_expr="* * * * *")
        assert (await _call(db, "get_schedule", schedule.id))["next_run_at"] is not None
    finally:
        if asynchronous:
            await db.db_client.drop_database(db.db_name)
        else:
            db.db_client.drop_database(db.db_name)
        await _call(db, "close")


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_mongo_company_rows_keep_updated_at_through_system_writes(asynchronous, monkeypatch):
    url = os.getenv("AGNO_TEST_MONGO_URL")
    if not url:
        pytest.skip("AGNO_TEST_MONGO_URL is required")
    cls = AsyncMongoDb if asynchronous else MongoDb
    db = cls(db_url=url, db_name="scheduler_edit_time_" + uuid4().hex)
    clock = [5000]
    monkeypatch.setattr(time, "time", lambda: clock[0])

    def row(identifier, managed_by, updated_at):
        return Schedule(
            id=identifier,
            name=identifier,
            cron_expr="* * * * *",
            endpoint="/agents/writer/runs",
            managed_by=managed_by,
            target_type="agent" if managed_by else None,
            target_id="writer" if managed_by else None,
            next_run_at=1,
            created_at=10,
            updated_at=updated_at,
        ).to_dict()

    async def stamps():
        return {
            identifier: (await _call(db, "get_schedule", identifier)).get("updated_at")
            for identifier in ("company", "legacy", "ordinary")
        }

    try:
        for fields in (row("company", "company", 100), row("legacy", "company", None), row("ordinary", None, 100)):
            await _call(db, "create_schedule", fields)
        for _ in range(3):
            claimed = await _call(db, "claim_due_schedule", "worker")
            assert await _call(
                db,
                "release_schedule",
                claimed["id"],
                next_run_at=10**10,
                worker_id="worker",
                locked_at=claimed["locked_at"],
                preserve_updated_at=claimed["id"] != "ordinary",
            )
        assert await stamps() == {"company": 100, "legacy": None, "ordinary": 5000}

        clock[0] = 9000
        assert await _call(db, "disable_schedules_for_target", "agent", "writer", reason="target_archived") == 3
        assert await stamps() == {"company": 100, "legacy": None, "ordinary": 9000}

        clock[0] = 12000
        await _call(db, "update_schedule", "company", enabled=True, preserve_updated_at=True)
        assert (await stamps())["company"] == 100
        await _call(db, "update_schedule", "company", enabled=False)
        assert (await stamps())["company"] == 12000
    finally:
        if asynchronous:
            await db.db_client.drop_database(db.db_name)
        else:
            db.db_client.drop_database(db.db_name)
        await _call(db, "close")
