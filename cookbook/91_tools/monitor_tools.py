"""
Monitor Tools
=============================

Give an agent the ability to start and manage background watches.

Use this when you cannot know in advance what to watch. If you already know, call
MonitorManager.create() in code instead -- the tool exists for the cases where the
thing to watch only exists once someone asks: a folder they name, or a run that
was just started.

The agent names a path freely -- a path is data, bounded by base_dir -- but a
shell command must be one the operator declared, so it can never supply its own.

These tools write monitor rows; they do not run them. What runs a row is the
poller AgentOS starts.

Prerequisites:
    export OPENAI_API_KEY=...
    pip install agno watchfiles
    # A running AgentOS with monitors enabled, on this same database.
    # See cookbook/05_agent_os/26_monitor/06_agent_sets_it_up.py for a working setup.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.monitor import MonitorTools

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="monitor-tools-db",
    db_file="tmp/monitor_tools.db",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    id="monitor-demo",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        MonitorTools(
            db=db,
            watches={"disk_usage": "free space on the root filesystem"},
            base_dir="tmp/watched",
        ),
    ],
    instructions=[
        "You are a helpful assistant that can watch things in the background."
    ],
    db=db,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.cli_app(user="Developer", exit_on=["exit", "quit"], markdown=True)
