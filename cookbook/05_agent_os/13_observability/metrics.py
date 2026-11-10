"""
Refresh and Read AgentOS Metrics
================================

Create a persisted agent run, refresh daily aggregates through
POST /metrics/refresh, then read the stored result through GET /metrics.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/metrics.py
Try: Compare agent_runs_count and total_tokens after another run
"""

import asyncio

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Metrics App
# ---------------------------------------------------------------------------

AGENT_ID = "metrics-agent"
DB_ID = "observability-metrics-db"

db = SqliteDb(
    id=DB_ID,
    db_file="tmp/observability_metrics.db",
)

metrics_agent = Agent(
    id=AGENT_ID,
    name="Metrics Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Reply in one short sentence.",
)

agent_os = AgentOS(
    id="observability-metrics-os",
    description="Refresh and inspect daily AgentOS metrics.",
    db=db,
    agents=[metrics_agent],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Metrics Readback
# ---------------------------------------------------------------------------


async def run_metrics_demo() -> None:
    """Generate session data, refresh metrics, and read the aggregate."""
    await metrics_agent.arun(
        "Reply with a short statement about observable systems.",
        session_id="observability-metrics-session",
        user_id="observability-user",
    )

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
        refreshed_metrics = refresh_response.json()
        if not refreshed_metrics:
            raise RuntimeError("POST /metrics/refresh returned no daily aggregate")

        metrics_response = await client.get(
            "/metrics",
            params={"db_id": DB_ID},
        )
        metrics_response.raise_for_status()
        metrics_page = metrics_response.json()
        if not metrics_page["metrics"]:
            raise RuntimeError("GET /metrics returned no stored aggregate")

    latest = max(metrics_page["metrics"], key=lambda metric: metric["date"])
    if latest["agent_runs_count"] < 1:
        raise RuntimeError("The refreshed aggregate omitted the new agent run")

    print(f"POST /metrics/refresh returned {len(refreshed_metrics)} day(s)")
    print(f"GET /metrics returned {len(metrics_page['metrics'])} day(s)")
    print(f"Date: {latest['date']}")
    print(f"Agent runs: {latest['agent_runs_count']}")
    print(f"Agent sessions: {latest['agent_sessions_count']}")
    print(f"Users: {latest['users_count']}")
    print(f"Total tokens: {latest['token_metrics'].get('total_tokens', 0)}")


if __name__ == "__main__":
    asyncio.run(run_metrics_demo())
