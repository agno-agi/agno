"""Agent with SchedulerTools -- let the agent create its own schedules.

Instead of managing schedules via REST API or code, this example gives
the agent a SchedulerTools toolkit so it can create, list, and manage
recurring schedules through natural language.

Ask the agent things like:
    - "Run a daily health check every morning at 9am"
    - "Show me all my schedules"
    - "Disable the daily-health-check schedule"

Prerequisites:
    pip install agno[scheduler]
    # Start postgres: ./cookbook/scripts/run_pgvector.sh

Usage:
    # Terminal 1: Start the AgentOS server
    python cookbook/05_agent_os/scheduler/scheduler_tools_agent.py serve

    # Terminal 2: Talk to the agent
    python cookbook/05_agent_os/scheduler/scheduler_tools_agent.py chat
"""

import sys

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.scheduler import SchedulerTools

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="scheduler-tools-demo-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ---------------------------------------------------------------------------
# Agent with SchedulerTools
# ---------------------------------------------------------------------------

scheduler_agent = Agent(
    id="scheduler-agent",
    name="Scheduler Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        SchedulerTools(
            db=db,
            default_endpoint="/agents/scheduler-agent/runs",
            default_timezone="UTC",
        ),
    ],
    instructions=[
        "You are a helpful assistant that can schedule recurring tasks.",
        "When a user asks you to do something on a recurring basis, use the scheduler tools.",
        "Always confirm what you scheduled, including the cron expression and timezone.",
        "If the user asks to see schedules or run history, use the appropriate tool.",
    ],
    db=db,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def serve():
    """Start the AgentOS server with the scheduler enabled."""
    from agno.os import AgentOS

    app = AgentOS(
        agents=[scheduler_agent],
        db=db,
        scheduler=True,
        scheduler_poll_interval=15,
    ).get_app()

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7777)


def chat():
    """Interactive chat with the scheduler agent."""
    print("Chat with the Scheduler Agent (type 'quit' to exit)")
    print("Try: 'Schedule a daily greeting every morning at 9am'")
    print("-" * 50)
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message or message.lower() in ("quit", "exit"):
            break
        scheduler_agent.print_response(message)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve()
    elif len(sys.argv) > 1 and sys.argv[1] == "chat":
        chat()
    else:
        # Default: just show a single interaction
        scheduler_agent.print_response(
            "Schedule a daily health check that runs every morning at 9am UTC. "
            "Name it 'daily-health-check'."
        )
