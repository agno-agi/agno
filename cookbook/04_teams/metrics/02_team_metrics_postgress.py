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
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response
from rich.pretty import pprint

# Database configuration for metrics storage
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="team_metrics_sessions")


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

print("\n" + "=" * 80)
print("1. RUN METRICS (Metrics class - run-level aggregation)")
print("=" * 80)
if run_output.metrics:
    print(f"Type: {type(run_output.metrics).__name__}")
    pprint(run_output.metrics.to_dict())

    # Print per-model metrics breakdown if details exist
    if run_output.metrics.details:
        print("\n" + "-" * 80)
        print("PER-MODEL METRICS (details field):")
        print("-" * 80)
        for model_type, model_metrics_list in run_output.metrics.details.items():
            print(f"\n{model_type}:")
            for i, model_metrics in enumerate(model_metrics_list, 1):
                print(f"  Instance {i}:")
                pprint(model_metrics.to_dict())
else:
    print("No run metrics available")

print("\n" + "=" * 80)
print("2. MESSAGE METRICS (MessageMetrics class - only on assistant messages)")
print("=" * 80)
assistant_messages = (
    [m for m in run_output.messages if m.role == "assistant"]
    if run_output.messages
    else []
)
for i, message in enumerate(assistant_messages, 1):
    print(f"\nTeam Leader Assistant Message {i}:")
    if message.metrics is not None:
        print(f"  Type: {type(message.metrics).__name__}")
        pprint(message.metrics.to_dict())
    else:
        print("  No metrics (this shouldn't happen for assistant messages)")

# Check user messages don't have metrics
user_messages = (
    [m for m in run_output.messages if m.role == "user"] if run_output.messages else []
)
print(f"\nUser Messages (should have None metrics): {len(user_messages)}")
for i, message in enumerate(user_messages, 1):
    print(f"  User Message {i} metrics: {message.metrics}")

print("\n" + "=" * 80)
print("3. TOOL CALL METRICS (ToolCallMetrics class - time-only on tool executions)")
print("=" * 80)
if run_output.tools:
    for i, tool in enumerate(run_output.tools, 1):
        print(f"\nTool Execution {i}: {tool.tool_name}")
        if tool.metrics is not None:
            print(f"  Type: {type(tool.metrics).__name__}")
            pprint(tool.metrics.to_dict())
        else:
            print("  No metrics")
else:
    print("No tool executions in this run")

print("\n" + "=" * 80)
print("4. SESSION METRICS (SessionMetrics class - aggregated, no run-level timing)")
print("=" * 80)
session_metrics = team.get_session_metrics(session_id="team_metrics_demo")
if session_metrics:
    print(f"Type: {type(session_metrics).__name__}")
    pprint(session_metrics.to_dict())

    # Print per-model session metrics breakdown if details exist
    if session_metrics.details:
        print("\n" + "-" * 80)
        print("PER-MODEL SESSION METRICS (details field):")
        print("-" * 80)
        for i, model_metrics in enumerate(session_metrics.details, 1):
            print(f"\nModel Instance {i}:")
            pprint(model_metrics.to_dict())

    print("\nSession-level stats:")
    print(f"  Total runs: {session_metrics.total_runs}")
    print(
        f"  Average duration: {session_metrics.average_duration:.4f}s"
        if session_metrics.average_duration
        else "  Average duration: N/A"
    )
    print(f"  Total tokens: {session_metrics.total_tokens}")
else:
    print("No session metrics available")

print("\n" + "=" * 80)
print("5. TEAM MEMBER METRICS (from member_responses)")
print("=" * 80)
if run_output.member_responses:
    for i, member_response in enumerate(run_output.member_responses, 1):
        print(f"\nMember Response {i}:")
        if hasattr(member_response, "run_id"):
            print(f"  Run ID: {member_response.run_id}")
        if member_response.metrics:
            print(f"  Run Metrics Type: {type(member_response.metrics).__name__}")
            pprint(member_response.metrics.to_dict())

        if member_response.messages:
            assistant_messages = [
                m for m in member_response.messages if m.role == "assistant"
            ]
            for j, message in enumerate(assistant_messages, 1):
                print(f"\n  Member Assistant Message {j}:")
                if message.metrics is not None:
                    print(f"    Type: {type(message.metrics).__name__}")
                    pprint(message.metrics.to_dict())
else:
    print("No member responses in this run")
