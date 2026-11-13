"""An opt-in schedule is never visible to the poller as enabled, not even between two writes."""

import time

import pytest

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.scheduler import ScheduleManager


def test_disabled_insert_is_not_claimable_and_update_preserves_the_toggle(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "schedules.db"))
    manager = ScheduleManager(db)
    schedule = manager.create(name="evals", cron="0 14 * * *", endpoint="/evals", enabled_on_create=False)
    assert db.get_schedule(schedule.id)["enabled"] is False
    db.update_schedule(schedule.id, next_run_at=int(time.time()) - 60)
    assert db.claim_due_schedule(worker_id="poller") is None

    manager.enable(schedule.id)
    refreshed = manager.create(
        name="evals", cron="0 15 * * *", endpoint="/evals", enabled_on_create=False, if_exists="update"
    )
    assert refreshed.id == schedule.id and refreshed.enabled is True
    manager.disable(schedule.id)
    refreshed = manager.create(name="evals", cron="0 16 * * *", endpoint="/evals", if_exists="update")
    assert refreshed.enabled is False


@pytest.mark.parametrize("async_db", [False, True])
async def test_async_creation_and_update_preserve_operator_state(tmp_path, async_db):
    db = (AsyncSqliteDb if async_db else SqliteDb)(db_file=str(tmp_path / "schedules.db"))
    manager = ScheduleManager(db)
    try:
        schedule = await manager.acreate(name="evals", cron="0 14 * * *", endpoint="/evals", enabled_on_create=False)
        assert schedule.enabled is False
        assert (await manager.aget(schedule.id)).enabled is False
        await manager.aenable(schedule.id)
        refreshed = await manager.acreate(
            name="evals", cron="0 15 * * *", endpoint="/evals", enabled_on_create=False, if_exists="update"
        )
        assert refreshed.enabled is True
        await manager.adisable(schedule.id)
        unchanged = await manager.acreate(name="evals", cron="0 16 * * *", endpoint="/evals", if_exists="skip")
        assert unchanged.enabled is False
    finally:
        manager.close()
        if async_db:
            await db.close()


def test_default_remains_enabled(tmp_path):
    manager = ScheduleManager(SqliteDb(db_file=str(tmp_path / "schedules.db")))
    assert manager.create(name="daily", cron="0 9 * * *", endpoint="/runs").enabled is True
