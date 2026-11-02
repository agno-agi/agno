"""
Serve AgentOS Metrics
=====================

Run two agents, refresh the metrics through POST /metrics/refresh, read today's
OS metrics back through the /os/metrics routes, then serve them. The routes
return the sessions, runs, tokens, latency and models of a date range, read
from the agno_component_metrics and agno_user_metrics tables the AgentOS
calculates from its sessions and runs.

Prerequisites: OPENAI_API_KEY and ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/os_metrics.py
Try: Open http://localhost:7777/os/metrics/sessions (also /runs, /tokens,
     /latency and /models), optionally with ?user_id=observability-user
"""

import asyncio
from datetime import datetime, timezone

import httpx
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Metrics AgentOS
# ---------------------------------------------------------------------------

DB_ID = "observability-os-metrics-db"

db = PostgresDb(
    id=DB_ID,
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

researcher = Agent(
    id="metrics-researcher",
    name="Metrics Researcher",
    model=OpenAIResponses(id="gpt-5.6-luna"),
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


async def run_os_metrics_demo() -> None:
    """Run both agents, refresh the metrics, and read today's totals through the routes."""
    await researcher.arun(
        "Name one benefit of tracing.",
        session_id="metrics-researcher-session",
        user_id="observability-user",
    )
    await summarizer.arun(
        "Name one benefit of metrics.",
        session_id="metrics-summarizer-session",
        user_id="observability-user",
    )

    today = datetime.now(timezone.utc).date().isoformat()
    window = {"starting_date": today, "ending_date": today}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://agent-os",
    ) as client:
        refresh_response = await client.post(
            "/metrics/refresh",
            params={"db_id": DB_ID},
        )
        refresh_response.raise_for_status()

        os_metrics = {}
        for route in ["sessions", "runs", "tokens", "models"]:
            response = await client.get(f"/os/metrics/{route}", params=window)
            response.raise_for_status()
            os_metrics[route] = response.json()

    if os_metrics["runs"]["total_runs"] < 2:
        raise RuntimeError("The metrics omitted the new agent runs")

    print(f"Sessions today: {os_metrics['sessions']['total_sessions']}")
    print(f"Runs today: {os_metrics['runs']['total_runs']}")
    print(
        f"Completed runs today: {os_metrics['runs']['status_metrics'].get('COMPLETED', 0)}"
    )
    print(f"Tokens today: {os_metrics['tokens']['total_tokens']}")
    for model in os_metrics["models"]["models"]:
        print(f"- {model['model_id']}: {model['runs_count']} run(s)")


if __name__ == "__main__":
    asyncio.run(run_os_metrics_demo())
    agent_os.serve(app=app)
