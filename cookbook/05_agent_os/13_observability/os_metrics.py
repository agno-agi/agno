"""
Serve AgentOS Metrics
=====================

Run two agents on different models, print today's OS metrics, then serve them.
The /os/metrics routes return the sessions, runs, tokens, latency and models of a
date range, read from the agno_os_metrics and agno_os_metrics_totals tables the
AgentOS builds from its sessions and runs.

Prerequisites: OPENAI_API_KEY and ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/os_metrics.py
Try: Open http://localhost:7777/os/metrics/sessions (also /runs, /tokens,
     /latency and /models), optionally with ?user_id=observability-user
"""

from datetime import datetime, timezone

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Metrics AgentOS
# ---------------------------------------------------------------------------

db = PostgresDb(
    id="observability-os-metrics-db",
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
    id="observability-os-metrics-os",
    description="AgentOS serving the OS metrics routes.",
    db=db,
    agents=[researcher, summarizer],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Metrics AgentOS
# ---------------------------------------------------------------------------


def run_os_metrics_demo() -> None:
    """Run both agents, refresh the OS metrics, and read today's totals."""
    researcher.run(
        "Name one benefit of tracing.",
        session_id="metrics-researcher-session",
        user_id="observability-user",
    )
    summarizer.run(
        "Name one benefit of metrics.",
        session_id="metrics-summarizer-session",
        user_id="observability-user",
    )

    db.refresh_os_metrics()
    today = datetime.now(timezone.utc).date()
    totals, _ = db.get_os_metrics_totals(starting_date=today, ending_date=today)
    if totals["runs_count"] < 2:
        raise RuntimeError("The OS metrics omitted the new agent runs")

    print(f"Sessions today: {totals['sessions_count']}")
    print(f"Runs today: {totals['runs_count']}")
    print(f"Completed runs today: {totals['status_metrics'].get('COMPLETED', 0)}")
    print(f"Tokens today: {totals['total_tokens']}")
    for model in totals["model_metrics"]:
        print(f"- {model['model_id']}: {model['count']} run(s)")


if __name__ == "__main__":
    run_os_metrics_demo()
    agent_os.serve(app=app)
