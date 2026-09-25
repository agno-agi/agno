"""
Serve AgentOS Metrics
=====================

Serve two agents on different models. After they run, the /os/metrics routes
return the sessions, runs, tokens, latency and models of a date range, read from
the agno_os_metrics table the AgentOS builds from its sessions and runs.

Prerequisites: OPENAI_API_KEY and ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/os_metrics.py
Try: Run both agents, then open http://localhost:7777/os/metrics/sessions (also
     /runs, /tokens, /latency and /models), optionally with ?user_id=<id>
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Metrics AgentOS
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="observability-metrics-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
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
    description="AgentOS serving the OS metrics routes.",
    db=db,
    agents=[researcher, summarizer],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Metrics AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
