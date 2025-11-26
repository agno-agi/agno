"""Test all four metrics types: ToolCallMetrics, MessageMetrics, Metrics, SessionMetrics"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from rich.pretty import pprint

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=InMemoryDb(),
    markdown=True,
    tools=[DuckDuckGoTools()],
    session_id="metrics-test-session",
)

# Run the agent to generate metrics
agent.print_response(
    "Write a 2 sentence horror story about the latest news on AI", stream=True
)

run_output = agent.get_last_run_output()

print("\n" + "=" * 80)
print("1. RUN METRICS (Metrics class - run-level aggregation)")
print("=" * 80)
if run_output.metrics:
    print(f"Type: {type(run_output.metrics).__name__}")
    pprint(run_output.metrics.to_dict())
else:
    print("No run metrics available")

print("\n" + "=" * 80)
print("2. MESSAGE METRICS (MessageMetrics class - only on assistant messages)")
print("=" * 80)
assistant_messages = [m for m in run_output.messages if m.role == "assistant"]
for i, message in enumerate(assistant_messages, 1):
    print(f"\nAssistant Message {i}:")
    if message.metrics is not None:
        print(f"  Type: {type(message.metrics).__name__}")
        pprint(message.metrics.to_dict())
    else:
        print("  No metrics (this shouldn't happen for assistant messages)")

# Check user messages don't have metrics
user_messages = [m for m in run_output.messages if m.role == "user"]
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
session_metrics = agent.get_session_metrics()
if session_metrics:
    print(f"Type: {type(session_metrics).__name__}")
    pprint(session_metrics.to_dict())
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
print("SUMMARY")
print("=" * 80)
print("✓ Run metrics (Metrics): Aggregated tokens + run-level timing")
print(
    "✓ Message metrics (MessageMetrics): Only on assistant messages, token consumption"
)
print(
    "✓ Tool metrics (ToolCallMetrics): Only time fields (duration, start_time, end_time)"
)
print(
    "✓ Session metrics (SessionMetrics): Aggregated tokens + average_duration, no run-level timing"
)
print("✓ User/system/tool messages: No metrics (None)")
