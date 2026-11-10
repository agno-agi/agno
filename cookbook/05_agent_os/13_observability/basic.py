"""
Enable AgentOS Tracing
======================

Enable OpenTelemetry tracing for a served agent with one AgentOS flag. Agent
runs, model calls, and tool calls become spans; the same flag also covers teams
and workflows registered with the OS.

Prerequisites: OPENAI_API_KEY is needed only to run the served agent
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/basic.py
Try: Open http://localhost:7777/traces and /traces/filter-schema
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Traced AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="observability-basic-db",
    db_file="tmp/observability_basic.db",
)

traced_agent = Agent(
    id="traced-assistant",
    name="Traced Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer operational questions clearly and concisely.",
)

agent_os = AgentOS(
    id="observability-basic-os",
    description="AgentOS with OpenTelemetry tracing stored in SQLite.",
    db=db,
    agents=[traced_agent],
    tracing=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Traced AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
