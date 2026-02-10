"""Running the scheduler inside AgentOS with programmatic schedule creation.

This example demonstrates:
- Setting scheduler=True on AgentOS to enable cron polling
- Using ScheduleManager to create schedules directly (no curl needed)
- The poller starts automatically on app startup and executes due schedules

Run with:
    .venvs/demo/bin/python cookbook/05_agent_os/scheduler/demo.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.scheduler import ScheduleManager
from agno.tools.websearch import WebSearchTools

# --- Setup ---
from agno.db.postgres import PostgresDb
# --- Setup ---

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url)

greeter = Agent(
    name="Greeter Agent",
    id="greeter",
    model=OpenAIChat(id="gpt-5"),
    instructions=["You are a friendly greeter."],
    db=db,
)

reporter = Agent(
    name="Reporter Agent",
    id="reporter",
    model=OpenAIChat(id="gpt-5"),
    instructions=["You summarize news headlines in 2-3 sentences."],
    tools =[WebSearchTools()],
    db=db,
)

# --- Create schedules programmatically ---

mgr = ScheduleManager(db)

# Create a schedule for the greeter agent (every 5 minutes)
greet_schedule = mgr.create(
    name="greet-every-5-min",
    cron="*/5 * * * *",
    endpoint="/agents/greeter/runs",
    payload={"message": "Say hello!"},
    description="Greet every 5 minutes",
    if_exists="update",
)
print(
    f"Schedule ready: {greet_schedule['name']} (next run: {greet_schedule['next_run_at']})"
)

# Create a schedule for the reporter agent (daily at 9 AM)
report_schedule = mgr.create(
    name="daily-news-report",
    cron="0 9 * * *",
    endpoint="/agents/reporter/runs",
    payload={"message": "Summarize today's top headlines."},
    description="Daily news summary at 9 AM UTC",
    if_exists="update",
)
print(
    f"Schedule ready: {report_schedule['name']} (next run: {report_schedule['next_run_at']})"
)

# --- Create AgentOS with scheduler enabled ---

agent_os = AgentOS(
    name="Scheduled OS",
    agents=[greeter, reporter],
    db=db,
    scheduler=True,
    scheduler_poll_interval=15,
)

# --- Run the server ---
# The poller will automatically pick up the schedules created above.

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(agent_os.get_app(), host="0.0.0.0", port=7777)
