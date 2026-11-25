"""A trigger on a schedule is one schedule row, and a restart leaves its next run where it was."""

import time

from agno.scheduler import ScheduleManager
from agno.triggers import Schedule, Trigger
from tests.unit.triggers.conftest import call


def daily(cron="0 2 * * *", timezone="UTC"):
    def declare(github, agent):
        return [Trigger(name="daily-report", on=Schedule(cron, timezone=timezone), agent=agent, input="Report.")]

    return declare


async def the_schedule(db):
    (schedule,) = [row for row in await ScheduleManager(db).alist_all() if row.name == "daily-report"]
    return schedule


async def test_a_restart_keeps_the_next_run_of_an_unchanged_schedule(make_os):
    os = await make_os(daily())
    schedule = await the_schedule(os.db)

    # The schedule is due: its time came while the app was down.
    due = int(time.time()) - 60
    await call(os.db, "update_schedule", schedule.id, next_run_at=due)

    await os.start()

    # It is still due, so it runs now and not a day later.
    assert (await the_schedule(os.db)).next_run_at == due


async def test_a_restart_still_stores_what_else_the_trigger_changed(make_os):
    os = await make_os(daily())
    schedule = await the_schedule(os.db)
    due = int(time.time()) - 60
    await call(os.db, "update_schedule", schedule.id, next_run_at=due)

    def changed(github, agent):
        return [
            Trigger(
                name="daily-report",
                on=Schedule("0 2 * * *"),
                agent=agent,
                input="Report, with numbers.",
                description="The daily report",
                timeout_seconds=120,
            )
        ]

    await make_os(changed)

    stored = await the_schedule(os.db)
    assert stored.id == schedule.id and stored.next_run_at == due
    assert stored.payload["message"] == "Report, with numbers."
    assert stored.description == "The daily report" and stored.timeout_seconds == 120


async def test_a_changed_cron_or_timezone_sets_a_new_next_run(make_os):
    os = await make_os(daily())
    schedule = await the_schedule(os.db)
    due = int(time.time()) - 60
    await call(os.db, "update_schedule", schedule.id, next_run_at=due)

    await make_os(daily(cron="30 4 * * *"))
    moved = await the_schedule(os.db)
    assert moved.cron_expr == "30 4 * * *" and moved.next_run_at > time.time()

    await call(os.db, "update_schedule", schedule.id, next_run_at=due)
    await make_os(daily(cron="30 4 * * *", timezone="Asia/Kolkata"))
    moved = await the_schedule(os.db)
    assert moved.timezone == "Asia/Kolkata" and moved.next_run_at > time.time()
