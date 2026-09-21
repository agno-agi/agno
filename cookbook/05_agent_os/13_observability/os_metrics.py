"""
Serve AgentOS Metrics
=====================

Serve two agents on different models. After they run, GET /os/metrics
returns the model usage breakdown that backs the homepage metrics card.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/os_metrics.py
Try: Run both agents, then open http://localhost:7777/os/metrics?days=7
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Metrics AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="observability-metrics-db",
    db_file="tmp/observability_metrics.db",
)

researcher = Agent(
    id="metrics-researcher",
    name="Metrics Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Reply in one short sentence.",
)

summarizer = Agent(
    id="metrics-summarizer",
    name="Metrics Summarizer",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Reply in one short sentence.",
)

agent_os = AgentOS(
    id="observability-metrics-os",
    description="AgentOS serving model usage metrics.",
    db=db,
    agents=[researcher, summarizer],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Metrics AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
