"""
Scheduler Tools
=============================

Give an agent the ability to create and manage recurring schedules.

The agent can convert natural language requests like "do this every day at 9am"
into cron-based schedules that run via the AgentOS scheduler infrastructure.

Prerequisites:
    pip install agno[scheduler]
    # A running AgentOS server with scheduler enabled
    # See cookbook/05_agent_os/scheduler/scheduler_tools_agent.py for full setup
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.scheduler import SchedulerTools

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="scheduler-tools-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    id="scheduler-demo",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        SchedulerTools(
            db=db,
            default_endpoint="/agents/scheduler-demo/runs",
        ),
    ],
    instructions=["You are a helpful assistant that can schedule recurring tasks."],
    db=db,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Schedule a daily weather briefing every weekday at 8:30am EST"
    )
