"""
Basic Scheduler Example

This example shows how to enable the scheduler in AgentOS.
The scheduler polls for due schedules and executes them automatically.

Requirements:
    pip install agno[scheduler]

Run:
    python cookbook/05_agent_os/scheduler/01_basic_scheduler.py

Then create a schedule via API:
    curl -X POST http://localhost:7777/schedules \
      -H "Content-Type: application/json" \
      -d '{
        "name": "test-schedule",
        "endpoint": "/agents/hello-agent/runs",
        "method": "POST",
        "payload": {"message": "Hello from scheduler!"},
        "cron_expr": "* * * * *"
      }'
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Create a simple agent
agent = Agent(
    id="hello-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a friendly assistant. Respond with a brief greeting.",
)

# Create a SQLite database for persistence
db = SqliteDb(db_file="scheduler_example.db")

# Create AgentOS with scheduler enabled
agent_os = AgentOS(
    agents=[agent],
    db=db,
    enable_scheduler=True,  # Enable the built-in scheduler
    scheduler_poll_interval=10,  # Check for due schedules every 10 seconds
)

if __name__ == "__main__":
    print("Starting AgentOS with scheduler enabled...")
    print("Create schedules via POST /schedules")
    print("List schedules via GET /schedules")
    app = agent_os.get_app()
    agent_os.serve(app, port=7777)
