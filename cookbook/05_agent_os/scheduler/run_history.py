"""Viewing and analyzing schedule run history.

This example demonstrates:
- Creating schedules and simulating run records
- Using SchedulerConsole.show_runs() for Rich-formatted run history
- Querying run history with pagination
- Understanding run statuses (success, failed, running, paused)
"""

import time
from uuid import uuid4

from agno.db.sqlite import SqliteDb
from agno.scheduler import ScheduleManager
from agno.scheduler.cli import SchedulerConsole

# --- Setup ---

db = SqliteDb(id="run-history-demo", db_file="tmp/run_history_demo.db")
mgr = ScheduleManager(db)
console = SchedulerConsole(mgr)

# --- Create a schedule ---

schedule = mgr.create(
    name="monitored-task",
    cron="*/5 * * * *",
    endpoint="/agents/monitor/runs",
    description="A schedule with run history to inspect",
    payload={"message": "Run health check"},
    max_retries=2,
    retry_delay_seconds=30,
)
print(f"Created schedule: {schedule.name} (id={schedule.id})")

# --- Simulate some run records by inserting directly ---
# In production, the ScheduleExecutor creates these automatically.
# Here we insert them manually to demonstrate the history display.

now = int(time.time())

# Simulate 3 runs with different statuses
run_records = [
    {
        "id": str(uuid4()),
        "schedule_id": schedule.id,
        "attempt": 1,
        "triggered_at": now - 600,
        "completed_at": now - 590,
        "status": "success",
        "status_code": 200,
        "run_id": str(uuid4()),
        "session_id": str(uuid4()),
        "error": None,
        "created_at": now - 600,
    },
    {
        "id": str(uuid4()),
        "schedule_id": schedule.id,
        "attempt": 1,
        "triggered_at": now - 300,
        "completed_at": now - 280,
        "status": "failed",
        "status_code": 500,
        "run_id": str(uuid4()),
        "session_id": None,
        "error": "Internal server error",
        "created_at": now - 300,
    },
    {
        "id": str(uuid4()),
        "schedule_id": schedule.id,
        "attempt": 2,
        "triggered_at": now - 240,
        "completed_at": now - 230,
        "status": "success",
        "status_code": 200,
        "run_id": str(uuid4()),
        "session_id": str(uuid4()),
        "error": None,
        "created_at": now - 240,
    },
]

for record in run_records:
    db.create_schedule_run(record)

# --- Display run history with Rich ---

print("\n=== Run History (Rich Table) ===\n")
console.show_runs(schedule.id)

# --- Query runs programmatically ---

print("\n=== Run History (Programmatic) ===\n")
runs = mgr.get_runs(schedule.id, limit=10)
print(f"Total runs: {len(runs)}")
for run in runs:
    status = run.status
    attempt = run.attempt
    error = run.error or "-"
    print(f"  Attempt {attempt}: {status} (error={error})")

# --- Pagination ---

print("\n=== Paginated (limit=2, offset=0) ===\n")
page1 = mgr.get_runs(schedule.id, limit=2, offset=0)
print(f"Page 1: {len(page1)} runs")

page2 = mgr.get_runs(schedule.id, limit=2, offset=2)
print(f"Page 2: {len(page2)} runs")

# --- Cleanup ---

mgr.delete(schedule.id)
print("\nSchedule and runs deleted.")
