from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager, UserMemory
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

memory_db = PostgresDb(db_url=db_url)

memory = MemoryManager(model=OpenAIChat(id="gpt-5-mini"), db=memory_db)

john_doe_id = "john_doe@example.com"
memory.add_user_memory(
    memory=UserMemory(memory="The user enjoys hiking in the mountains on weekends"),
    user_id=john_doe_id,
)
memory.add_user_memory(
    memory=UserMemory(
        memory="The user enjoys reading science fiction novels before bed"
    ),
    user_id=john_doe_id,
)
print("John Doe's memories:")
pprint(memory.get_user_memories(user_id=john_doe_id))

memories = memory.search_user_memories(
    user_id=john_doe_id, limit=1, retrieval_method="last_n"
)
print("\nJohn Doe's last_n memories:")
pprint(memories)

memories = memory.search_user_memories(
    user_id=john_doe_id, limit=1, retrieval_method="first_n"
)
print("\nJohn Doe's first_n memories:")
pprint(memories)

memories = memory.search_user_memories(
    user_id=john_doe_id,
    query="What does the user like to do on weekends?",
    retrieval_method="agentic",
)
print("\nJohn Doe's memories similar to the query (agentic):")
pprint(memories)

# Create an agent with memory manager to generate metrics
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    memory_manager=memory,
    db=memory_db,
    markdown=True,
    session_id="memory-metrics-test-session",
    user_id=john_doe_id,
)

# Run the agent to generate metrics
agent.print_response(
    "Based on my memories, what activities do I enjoy? Can you suggest a weekend activity for me?",
    stream=True,
)

run_output = agent.get_last_run_output()

print("\n" + "=" * 80)
print("1. RUN METRICS (Metrics class - run-level aggregation)")
print("=" * 80)
if run_output.metrics:
    print(f"Type: {type(run_output.metrics).__name__}")
    metrics_dict = run_output.metrics.to_dict()
    pprint(metrics_dict)

    # Show details if available
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
