"""
Manage Schedules with Python
============================

Use synchronous and genuinely asynchronous Postgres adapters with
ScheduleManager, including safe cron updates, paging, and validation errors.

Prerequisites: ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/03_manage_with_python.py
Try: Change page, cron_expr, timezone, retry, and timeout values
"""

import asyncio
import os

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.scheduler import ScheduleManager

# ---------------------------------------------------------------------------
# Create Sync and Async Schedule Managers
# ---------------------------------------------------------------------------

SYNC_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://ai:ai@localhost:5532/ai",
)
ASYNC_DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL",
    "postgresql+psycopg_async://ai:ai@localhost:5532/ai",
)
SCHEDULES_TABLE = "python_scheduler_schedules"
RUNS_TABLE = "python_scheduler_runs"

sync_db = PostgresDb(
    id="python-scheduler-sync-db",
    db_url=SYNC_DATABASE_URL,
    schedules_table=SCHEDULES_TABLE,
    schedule_runs_table=RUNS_TABLE,
)
sync_manager = ScheduleManager(sync_db)


def reset_sync_schedules() -> None:
    """Delete rows owned by this isolated lesson table."""
    for schedule in sync_manager.list(limit=1000, page=1):
        sync_manager.delete(schedule.id)


def run_sync_manager() -> None:
    """Exercise sync CRUD, pagination, configuration, and validation."""
    reset_sync_schedules()
    agent_schedule = sync_manager.create(
        name="new-york-research",
        cron="0 7 * * 1-5",
        endpoint="/agents/research-agent/runs",
        description="Weekday research digest.",
        payload={"message": "Prepare the weekday research digest."},
        timezone="America/New_York",
        timeout_seconds=180,
        max_retries=2,
        retry_delay_seconds=15,
    )
    team_schedule = sync_manager.create(
        name="utc-team-review",
        cron="0 16 * * 5",
        endpoint="/teams/review-team/runs",
        payload={"message": "Review this week's operational changes."},
    )
    workflow_schedule = sync_manager.create(
        name="nightly-workflow",
        cron="0 2 * * *",
        endpoint="/workflows/data-pipeline/runs",
        payload={"message": "Process the nightly data batch."},
        timeout_seconds=900,
    )

    first_page = sync_manager.list(limit=2, page=1)
    second_page = sync_manager.list(limit=2, page=2)
    if len(first_page) != 2 or len(second_page) != 1:
        raise RuntimeError("ScheduleManager list pagination returned wrong pages")

    sync_manager.disable(agent_schedule.id)
    previous_next_run = agent_schedule.next_run_at
    updated = sync_manager.update(
        agent_schedule.id,
        cron_expr="0 8 * * 1-5",
        description="Updated weekday research digest.",
    )
    if updated is None or updated.cron_expr != "0 8 * * 1-5":
        raise RuntimeError("ScheduleManager update requires cron_expr")
    enabled = sync_manager.enable(agent_schedule.id)
    if enabled is None or not enabled.enabled:
        raise RuntimeError("ScheduleManager did not re-enable the schedule")
    if enabled.next_run_at == previous_next_run:
        raise RuntimeError("Enable did not recompute the next run after cron update")

    history_page = sync_manager.get_runs(agent_schedule.id, limit=1, page=1)
    if history_page:
        raise RuntimeError("A never-executed schedule unexpectedly has run history")

    validation_errors = 0
    for name, cron, timezone in (
        ("invalid-cron", "not a cron", "UTC"),
        ("invalid-timezone", "0 9 * * *", "Mars/Olympus"),
        ("new-york-research", "0 9 * * *", "UTC"),
    ):
        try:
            sync_manager.create(
                name=name,
                cron=cron,
                endpoint="/health",
                method="GET",
                timezone=timezone,
            )
        except ValueError:
            validation_errors += 1
    if validation_errors != 3:
        raise RuntimeError("Expected cron, timezone, and duplicate-name errors")

    print(f"Sync schedule: {enabled.id}")
    print(f"Cron: {enabled.cron_expr}")
    print(f"Timezone: {enabled.timezone}")
    print(
        "Retry/timeout: "
        f"{enabled.max_retries}/{enabled.retry_delay_seconds}/{enabled.timeout_seconds}"
    )
    print(f"Schedule pages: {len(first_page)}, {len(second_page)}")
    print(f"History page 1: {len(history_page)}")
    print(f"Validation errors: {validation_errors}")

    for schedule in (agent_schedule, team_schedule, workflow_schedule):
        sync_manager.delete(schedule.id)


async def run_async_manager() -> None:
    """Exercise the real async ScheduleManager API with AsyncPostgresDb."""
    async_db = AsyncPostgresDb(
        id="python-scheduler-async-db",
        db_url=ASYNC_DATABASE_URL,
        schedules_table=SCHEDULES_TABLE,
        schedule_runs_table=RUNS_TABLE,
    )
    async_manager = ScheduleManager(async_db)
    schedule = None
    try:
        schedule = await async_manager.acreate(
            name="async-morning-brief",
            cron="0 9 * * *",
            endpoint="/agents/brief-agent/runs",
            description="Created through the asynchronous manager.",
            payload={"message": "Prepare the asynchronous morning brief."},
        )
        listed = await async_manager.alist(limit=1, page=1)
        fetched = await async_manager.aget(schedule.id)
        await async_manager.adisable(schedule.id)
        updated = await async_manager.aupdate(
            schedule.id,
            cron_expr="0 10 * * *",
        )
        enabled = await async_manager.aenable(schedule.id)
        runs = await async_manager.aget_runs(schedule.id, limit=1, page=1)

        if len(listed) != 1 or fetched is None:
            raise RuntimeError("Async schedule list/get failed")
        if updated is None or updated.cron_expr != "0 10 * * *":
            raise RuntimeError("Async cron_expr update failed")
        if enabled is None or not enabled.enabled or runs:
            raise RuntimeError("Async enable/history result was unexpected")

        print(f"Async schedule: {enabled.id}")
        print(f"Async cron: {enabled.cron_expr}")
        print(f"Async page 1: {len(listed)}")
        print(f"Async history page 1: {len(runs)}")
    finally:
        if schedule is not None:
            await async_manager.adelete(schedule.id)
        async_manager.close()
        await async_db.close()


# ---------------------------------------------------------------------------
# Run Python Schedule Management
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        run_sync_manager()
        asyncio.run(run_async_manager())
    finally:
        sync_manager.close()
        sync_db.close()
