"""Test all four metrics types: ToolCallMetrics, MessageMetrics, Metrics, SessionMetrics"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.models.openai.responses import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

class Response(BaseModel):
    story_name: str = Field(description="The name of the story")
    story_description: str = Field(description="The description of the story")
    story_content: str = Field(description="The content of the story")

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=OpenAIResponses(id="gpt-4.1"),
    output_model=OpenAIChat(id="o3-mini"),
    parser_model=OpenAIChat(id="gpt-5-mini"),

    db=db,
    markdown=True,
    tools=[DuckDuckGoTools()],
    session_id="metrics-test-session",
    output_schema=Response,
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



{'input_tokens': 589, 'output_tokens': 159, 'total_tokens': 748, 'time_to_first_token': 5.490511832991615, 'duration': 8.73270150006283}

{'input_tokens': None, 'output_tokens': None, 'total_tokens': None, 'time_to_first_token': 5.490511832991615, 'duration': 8.73270150006283}

# How to handle retries?
# if we track, should we have a way to display it? RunOutput contains only the last successful run metrics.

# RUN METRICS
{
    'input_tokens': 589, # total input tokens summed from all models in the details section
    'output_tokens': 159, # total output tokens summed from all models in the details section
    'total_tokens': 748, # total tokens summed from all models in the details section
    'time_to_first_token': 5.490511832991615, # time to first token from the first model called in the run
    'duration': 8.73270150006283, # total duration of the run
    'details': {
        "model":[{
            "id": "gpt-5",
            "provider": "openai",
            "input_tokens": 589,
            "output_tokens": 159,
            "total_tokens": 748,
            "time_to_first_token": 5.490511832991615,
        }],
        "reasoning_model":[{
            "id": "claude-3-7-sonnet-latest",
            "provider": "anthropic",
            "input_tokens": 589,
            "output_tokens": 159,
            "total_tokens": 748,
            "time_to_first_token": 5.490511832991615,
        }],
        "session_summary_model":[{
            "id": "gpt-5",
            "provider": "openai",
            "input_tokens": 589,
            "output_tokens": 159,
            "total_tokens": 748,
            "time_to_first_token": 5.490511832991615,
        }],
        "context_compression_model":[{
            "id": "gpt-5",
            "provider": "openai",
            "input_tokens": 589,
            "output_tokens": 159,
            "total_tokens": 748,
            "time_to_first_token": 5.490511832991615,
        }],
        "culture_model":[{
            "id": "gpt-5",
            "provider": "openai",
            "input_tokens": 589,
            "output_tokens": 159,
            "total_tokens": 748,
            "time_to_first_token": 5.490511832991615,
        }],
        "memory_model":[{
            "id": "gpt-5",
            "provider": "openai",
            "input_tokens": 589,
            "output_tokens": 159,
            "total_tokens": 748,
            "time_to_first_token": 5.490511832991615,
        }],
    }
}

# SESSION METRICS

{
    'input_tokens': 1287,
    'output_tokens': 87,
    'total_tokens': 1374,
    'average_duration': 6.450697125052102,
    'total_runs': 2,
    'details': 
    [
        {
            "provider": "openai",
            "id": "gpt-5",
            "input_tokens": 1287,
            "output_tokens": 87,
            "total_tokens": 1374,
            "average_duration": 6.450697125052102,
            "total_runs": 1,
        },
        {
            "provider": "anthropic",
            "id": "claude-3-7-sonnet-latest",
            "input_tokens": 1287,
            "output_tokens": 87,
            "total_tokens": 1374,
            "average_duration": 6.450697125052102,
            "total_runs": 1,
        }
    ]
}