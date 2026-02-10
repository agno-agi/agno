"""Basic schedule creation and display using the Pythonic API.

This example demonstrates:
- Creating a ScheduleManager from a database
- Creating and listing schedules
- Using SchedulerConsole for Rich-formatted output
"""

from agno.db.sqlite import SqliteDb
from agno.scheduler import ScheduleManager
from agno.scheduler.cli import SchedulerConsole

# --- Setup ---

db = SqliteDb(id="scheduler-demo", db_file="tmp/scheduler_demo.db")
mgr = ScheduleManager(db)

# --- Create a schedule via the Pythonic API ---

schedule = mgr.create(
    name="daily-health-check",
    cron="0 9 * * *",
    endpoint="/agents/scheduled-agent/runs",
    description="Run the scheduled agent every day at 9 AM UTC",
    payload={"message": "What is the system health?"},
)

print(f"Created schedule: {schedule['name']} (id={schedule['id']})")
print(f"  Cron: {schedule['cron_expr']}")
print(f"  Endpoint: {schedule['endpoint']}")
print(f"  Next run: {schedule['next_run_at']}")

# --- List all schedules ---

schedules = mgr.list()
print(f"\nTotal schedules: {len(schedules)}")

# --- Display with Rich console ---

console = SchedulerConsole(mgr)
console.show_schedules()

# --- Cleanup ---

mgr.delete(schedule["id"])
print("\nSchedule deleted.")
