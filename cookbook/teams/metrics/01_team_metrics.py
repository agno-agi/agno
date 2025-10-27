"""
This example demonstrates how to access and analyze team metrics.

Shows how to retrieve detailed metrics for team execution, including
message-level metrics, session metrics, and member-specific metrics.

Prerequisites:
1. Run: cookbook/run_pgvector.sh (to start PostgreSQL)
2. Ensure PostgreSQL is running on localhost:5532
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.db.surrealdb import SurrealDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response
from rich.pretty import pprint

# Database configuration for metrics storage
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="team_metrics_sessions")


# Setup the SurrealDB database
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "agno"
SURREALDB_DATABASE = "agent_os_demo"

creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)

# Create stock research agent
stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("o3-mini"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools()],
)

# Create team with metrics tracking enabled
team = Team(
    name="Stock Research Team",
    model=OpenAIChat("o3-mini"),
    members=[stock_searcher],
    db=db,  # Database required for session metrics
    session_id="team_metrics_demo",
    markdown=True,
    show_members_responses=True,
    store_member_responses=True,
)

# Run the team and capture metrics
run_output = team.run("What is the stock price of NVDA")
pprint_run_response(run_output, markdown=True)

# Analyze team leader message metrics
print("=" * 50)
print("TEAM LEADER MESSAGE METRICS")
print("=" * 50)

if run_output.messages:
    for message in run_output.messages:
        if message.role == "assistant":
            if message.content:
                print(f"📝 Message: {message.content[:100]}...")
            elif message.tool_calls:
                print(f"🔧 Tool calls: {message.tool_calls}")

            print("-" * 30, "Metrics", "-" * 30)
            pprint(message.metrics)
            print("-" * 70)

# Analyze aggregated team metrics
print("=" * 50)
print("AGGREGATED TEAM METRICS")
print("=" * 50)
pprint(run_output.metrics)

# Analyze session-level metrics
print("=" * 50)
print("SESSION METRICS")
print("=" * 50)
pprint(team.get_session_metrics(session_id="team_metrics_demo"))

# Analyze individual member metrics
print("=" * 50)
print("TEAM MEMBER MESSAGE METRICS")
print("=" * 50)

if run_output.member_responses:
    for member_response in run_output.member_responses:
        if member_response.messages:
            for message in member_response.messages:
                if message.role == "assistant":
                    if message.content:
                        print(f"📝 Member Message: {message.content[:100]}...")
                    elif message.tool_calls:
                        print(f"🔧 Member Tool calls: {message.tool_calls}")

                    print("-" * 20, "Member Metrics", "-" * 20)
                    pprint(message.metrics)
                    print("-" * 60)
