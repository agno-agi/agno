"""Release fencing and on-demand cadence edits against real MongoDB."""

import os
from uuid import uuid4

import pytest

from agno.company.execution import _call
from agno.db.mongo import AsyncMongoDb, MongoDb
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
