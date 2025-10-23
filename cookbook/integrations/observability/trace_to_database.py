"""
Example demonstrating how to capture agent traces and store them in the database.

This example shows how to:
1. Set up tracing with the Agno database
2. Automatically capture traces for agent runs, model calls, and tool executions
3. Query traces from the database

Requirements:
    pip install agno opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools
from agno.tracing import setup_tracing

# Set up database
db = SqliteDb(db_file="tmp/traces.db")

# Set up tracing - this instruments ALL agents automatically
# All agent runs, model calls, and tool executions will be traced
setup_tracing(db=db)

# Create and use agent normally - tracing happens automatically!
agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    instructions="You are a stock price agent. Answer questions concisely.",
    markdown=True,
)

# Run the agent - traces will be captured automatically
print("=" * 60)
print("Running agent with automatic tracing...")
print("=" * 60)
agent.print_response("What is the current price of Tesla?")

# Query traces from database
print("\n" + "=" * 60)
print("Traces captured in database:")
print("=" * 60)

# Force flush traces to database before querying
from opentelemetry import trace as trace_api
tracer_provider = trace_api.get_tracer_provider()
if hasattr(tracer_provider, 'force_flush'):
    tracer_provider.force_flush(timeout_millis=5000)

try:
    # First, get ALL traces without filtering
    all_traces = db.get_traces(limit=20)
    if all_traces:
        print(f"\nFound {len(all_traces)} trace spans (unfiltered):")
        for trace in all_traces:
            indent = "  " * (0 if not trace.parent_span_id else 1)
            print(f"\n{indent}- {trace.name}")
            print(f"{indent}  Duration: {trace.duration_ms}ms")
            print(f"{indent}  Status: {trace.status_code}")
            print(f"{indent}  Agent ID: {trace.agent_id}")
            print(f"{indent}  Run ID: {trace.run_id}")
            print(f"{indent}  Session ID: {trace.session_id}")
            if trace.attributes:
                print(f"{indent}  Attributes (first 10):")
                for key, value in list(trace.attributes.items())[:10]:
                    print(f"{indent}    {key}: {value}")
    else:
        print("No traces found at all. Make sure openinference-instrumentation-agno is installed.")
        
    # Now try filtering by agent_id
    print(f"\n\nFiltering by agent_id={agent.id}:")
    agent_traces = db.get_traces(agent_id=agent.id, limit=20)
    if agent_traces:
        print(f"Found {len(agent_traces)} traces for this agent")
    else:
        print("No traces found when filtering by agent_id")
        
except Exception as e:
    print(f"Error querying traces: {e}")
    import traceback
    traceback.print_exc()

