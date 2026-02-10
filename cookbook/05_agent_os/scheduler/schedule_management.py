"""Full schedule management demo using the Pythonic API and Rich CLI.

This example demonstrates the complete lifecycle:
1. Create schedules
2. List and display schedules
3. Disable/enable schedules
4. Update schedule properties
5. View schedule details
6. Clean up
"""

from agno.db.sqlite import SqliteDb
from agno.scheduler import ScheduleManager
from agno.scheduler.cli import SchedulerConsole

# --- Setup ---

db = SqliteDb(id="schedule-mgmt-demo", db_file="tmp/schedule_mgmt_demo.db")
mgr = ScheduleManager(db)
console = SchedulerConsole(mgr)

# --- 1. Create schedules ---

print("=== Creating schedules ===\n")

sched1 = mgr.create(
    name="every-5-min",
    cron="*/5 * * * *",
    endpoint="/agents/my-agent/runs",
    description="Run agent every 5 minutes",
    payload={"message": "Quick check"},
)
console.show_schedule(sched1["id"])

sched2 = mgr.create(
    name="daily-report",
    cron="0 18 * * 1-5",
    endpoint="/agents/my-agent/runs",
    description="Generate daily report at 6 PM on weekdays",
    payload={"message": "Generate the daily report"},
    timezone="America/New_York",
)

sched3 = mgr.create(
    name="weekly-cleanup",
    cron="0 3 * * 0",
    endpoint="/agents/my-agent/runs",
    description="Weekly cleanup on Sunday at 3 AM",
    method="POST",
    max_retries=2,
    retry_delay_seconds=120,
)

# --- 2. List all schedules ---

print("\n=== All schedules ===\n")
console.show_schedules()

# --- 3. Disable a schedule ---

print("\n=== Disabling 'every-5-min' ===\n")
mgr.disable(sched1["id"])
disabled = mgr.get(sched1["id"])
print(f"  enabled: {disabled['enabled']}")

# --- 4. Re-enable ---

print("\n=== Re-enabling 'every-5-min' ===\n")
mgr.enable(sched1["id"])
enabled = mgr.get(sched1["id"])
print(f"  enabled: {enabled['enabled']}")
print(f"  next_run_at: {enabled['next_run_at']}")

# --- 5. Update schedule ---

print("\n=== Updating 'weekly-cleanup' description ===\n")
mgr.update(sched3["id"], description="Weekly maintenance and cleanup")
console.show_schedule(sched3["id"])

# --- 6. Filter by enabled ---

print("\n=== Only enabled schedules ===\n")
enabled_schedules = mgr.list(enabled=True)
print(f"  {len(enabled_schedules)} enabled schedule(s)")

# --- 7. Cleanup ---

print("\n=== Cleaning up ===\n")
for s in mgr.list():
    deleted = mgr.delete(s["id"])
    print(f"  Deleted {s['name']}: {deleted}")

remaining = mgr.list()
print(f"\nRemaining schedules: {len(remaining)}")
print("\nDone.")
