"""Basic schedule creation and display using the Pythonic API.

This example demonstrates:
- Creating an AgentOS with a database
- Using app.scheduler to create and list schedules
- Using SchedulerConsole for Rich-formatted output
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.scheduler.cli import SchedulerConsole

# --- Setup ---

db = SqliteDb(id="scheduler-demo", db_file="tmp/scheduler_demo.db")

agent = Agent(name="Scheduled Agent", db=db)

app = AgentOS(
    name="Scheduler Demo",
    agents=[agent],
    db=db,
)

# --- Create a schedule via the Pythonic API ---

schedule = app.scheduler.create(
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

schedules = app.scheduler.list()
print(f"\nTotal schedules: {len(schedules)}")

# --- Display with Rich console ---

console = SchedulerConsole(app.scheduler)
console.show_schedules()

# --- Cleanup ---

app.scheduler.delete(schedule["id"])
print("\nSchedule deleted.")
