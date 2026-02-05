"""
Schedule Workflow Example

This example demonstrates scheduling workflow executions.
Workflows can be scheduled just like agents.

Requirements:
    pip install agno[scheduler]

Run:
    python cookbook/05_agent_os/scheduler/03_schedule_workflow.py
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.workflow import Step, Workflow


# Create database and AgentOS
db = SqliteDb(db_file="scheduled_workflow.db")

researcher = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a researcher. Gather key facts about the given topic.",
)

writer = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a report writer. Write a clear summary based on research.",
)

workflow = Workflow(
    name="report-workflow",
    id="report-workflow",
    description="Generate a comprehensive report with multiple steps",
    steps=[
        Step(name="research", agent=researcher),
        Step(name="write", agent=writer),
    ],
)

agent_os = AgentOS(
    workflows=[workflow],
    db=db,
    enable_scheduler=True,
    scheduler_poll_interval=10,
)

if __name__ == "__main__":
    print("Starting AgentOS with scheduled workflow...")
    print("\nAvailable workflow:")
    print("  - report-workflow: Generates research-based reports")
    print("\nCreate a schedule to run the workflow:")
    print("""
    curl -X POST http://localhost:7777/schedules \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "weekly-ai-report",
        "endpoint": "/workflows/report-workflow/runs",
        "method": "POST",
        "payload": {"message": "Latest AI developments"},
        "cron_expr": "0 9 * * 1"
      }'
    """)

    app = agent_os.get_app()
    agent_os.serve(app, port=7777)
