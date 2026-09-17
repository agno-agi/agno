"""
Serve AgentOS Insights
======================

Serve two agents on different models. After they run, GET /insights/metrics
returns the model usage breakdown that backs the homepage insight card.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/insights.py
Try: Run both agents, then open http://localhost:7777/insights/metrics?days=7
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Insights AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="observability-insights-db",
    db_file="tmp/observability_insights.db",
)

researcher = Agent(
    id="insights-researcher",
    name="Insights Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Reply in one short sentence.",
)

summarizer = Agent(
    id="insights-summarizer",
    name="Insights Summarizer",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    instructions="Reply in one short sentence.",
)

agent_os = AgentOS(
    id="observability-insights-os",
    description="AgentOS serving model usage insights.",
    db=db,
    agents=[researcher, summarizer],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Insights AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
