"""
Team Session Metrics
=============================

Demonstrates session-level metrics for teams with PostgreSQL persistence.
Metrics accumulate across multiple team runs within the same session.

Run: ./cookbook/scripts/run_pgvector.sh
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="team_metrics_sessions")

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
assistant = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Helpful assistant that answers questions.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Research Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[assistant],
    db=db,
    session_id="team_session_metrics_demo",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # First run
    run_output_1 = team.run("What is the capital of Japan?")
    print("=" * 50)
    print("RUN 1 METRICS")
    print("=" * 50)
    pprint(run_output_1.metrics)

    # Second run on the same session
    run_output_2 = team.run("What about South Korea?")
    print("=" * 50)
    print("RUN 2 METRICS")
    print("=" * 50)
    pprint(run_output_2.metrics)

    # Session metrics aggregate both runs
    print("=" * 50)
    print("SESSION METRICS (accumulated)")
    print("=" * 50)
    session_metrics = team.get_session_metrics()
    pprint(session_metrics)
