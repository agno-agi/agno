"""
Example demonstrating the two-table trace design with Agno.

This example shows:
1. How traces and spans are stored in separate tables
2. How to query traces (high-level view)
3. How to drill down to spans for a specific trace
4. The hierarchical relationship between traces and spans

Requirements:
    pip install agno opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno
"""

import time  # noqa

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools
from agno.tracing import setup_tracing
from agno.utils.pprint import pprint_run_response

# Set up database
db = SqliteDb(db_file="tmp/traces.db")

# Set up tracing - this instruments ALL agents automatically
setup_tracing(db=db)

agent = Agent(
    name="HackerNews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    instructions="You are a hacker news agent. Answer questions concisely.",
    markdown=True,
)

# Run the agent - traces will be captured automatically
print("=" * 60)
print("Running agent with automatic tracing...")
print("=" * 60)
response = agent.run("What is the latest news on AI?")
pprint_run_response(response)

# Query traces and spans from database
print("\n" + "=" * 60)
print("Traces and Spans in Database:")
print("=" * 60)

## If using BatchSpanProcessor, we need to wait for the traces to be flushed to the database before querying
# time.sleep(5) # Uncomment this if using BatchSpanProcessor

try:
    # Get the trace for this run
    trace = db.get_trace(run_id=response.run_id)

    if not trace:
        print(
            "\n❌ No trace found. Make sure openinference-instrumentation-agno is installed."
        )
    else:
        print("\n📊 Found trace for run")

        print(f"\n🔍 Trace ID: {trace.trace_id[:16]}...")
        print(f"   Name: {trace.name}")
        print(f"   Status: {trace.status}")
        print(f"   Duration: {trace.duration_ms}ms")
        print(f"   Total Spans: {trace.total_spans}")
        if trace.error_count > 0:
            print(f"   Errors: {trace.error_count}")
        if trace.agent_id:
            print(f"   Agent ID: {trace.agent_id}")
        if trace.run_id:
            print(f"   Run ID: {trace.run_id[:16]}...")
        if trace.session_id:
            print(f"   Session ID: {trace.session_id[:16]}...")

        # Get all spans for this trace
        spans = db.get_spans(trace_id=trace.trace_id)
        print(f"\n   All spans in this trace ({len(spans)} spans):")

        for span in sorted(spans, key=lambda s: s.start_time):
            indent = "  " if span.parent_span_id else ""
            duration = (
                f"{span.duration_ms}ms"
                if span.duration_ms < 1000
                else f"{span.duration_ms / 1000:.1f}s"
            )
            print(f"      {indent}- {span.name} ({duration}) [{span.status_code}]")

            # Show span kind and key attributes
            span_kind = span.attributes.get("openinference.span.kind")
            if span_kind:
                print(f"        {indent}  Kind: {span_kind}")

            # Show detailed attributes based on span kind
            if span_kind == "AGENT":
                # Agent-specific attributes
                if span.attributes.get("input.value"):
                    input_val = span.attributes["input.value"]
                    if len(str(input_val)) < 80:
                        print(f"        {indent}  Input: {input_val}")
                if span.attributes.get("output.value"):
                    output_val = span.attributes["output.value"]
                    if len(str(output_val)) < 80:
                        print(f"        {indent}  Output: {output_val}")

            elif span_kind == "TOOL":
                # Tool-specific attributes
                tool_name = span.attributes.get("tool.name")
                if tool_name:
                    print(f"        {indent}  Tool: {tool_name}")
                params = span.attributes.get("tool.parameters")
                if params:
                    print(f"        {indent}  Input: {params}")
                output = span.attributes.get("output.value")
                if output:
                    output_str = str(output)[:100]
                    print(
                        f"        {indent}  Output: {output_str}{'...' if len(str(output)) > 100 else ''}"
                    )

            elif span_kind == "LLM":
                # LLM-specific attributes
                model_name = span.attributes.get(
                    "llm.model_name"
                ) or span.attributes.get("gen_ai.request.model")
                if model_name:
                    print(f"        {indent}  Model: {model_name}")

                # Token usage
                input_tokens = span.attributes.get(
                    "llm.token_count.prompt"
                ) or span.attributes.get("gen_ai.usage.prompt_tokens")
                output_tokens = span.attributes.get(
                    "llm.token_count.completion"
                ) or span.attributes.get("gen_ai.usage.completion_tokens")
                if input_tokens or output_tokens:
                    print(
                        f"        {indent}  Tokens: {input_tokens or 0} in, {output_tokens or 0} out"
                    )

                # Show input/output messages (first few)
                input_messages = span.attributes.get("llm.input_messages")
                if (
                    input_messages
                    and isinstance(input_messages, list)
                    and len(input_messages) > 0
                ):
                    last_msg = input_messages[-1]
                    if isinstance(last_msg, dict) and "message.content" in last_msg:
                        content = last_msg["message.content"]
                        if len(str(content)) < 80:
                            print(f"        {indent}  Prompt: {content}")

            # Show any error messages
            if span.status_code == "ERROR" and span.status_message:
                print(f"        {indent}  ❌ Error: {span.status_message}")

            # Show important generic attributes (excluding the ones we already showed)
            important_attrs = {
                "session.id": "Session",
                "user.id": "User",
                "agno.agent.id": "Agent",
                "agno.run.id": "Run",
            }
            for attr_key, label in important_attrs.items():
                if attr_key in span.attributes and span.attributes[attr_key]:
                    val = span.attributes[attr_key]
                    # Truncate long IDs
                    if len(str(val)) > 16:
                        val = f"{str(val)[:16]}..."
                    print(f"        {indent}  {label}: {val}")

            # Show all other attributes (for debugging - can be commented out)
            shown_keys = {
                "openinference.span.kind",
                "input.value",
                "output.value",
                "tool.name",
                "tool.parameters",
                "llm.model_name",
                "gen_ai.request.model",
                "llm.token_count.prompt",
                "llm.token_count.completion",
                "gen_ai.usage.prompt_tokens",
                "gen_ai.usage.completion_tokens",
                "llm.input_messages",
                "session.id",
                "user.id",
                "agno.agent.id",
                "agno.run.id",
            }
            other_attrs = {
                k: v for k, v in span.attributes.items() if k not in shown_keys
            }
            if other_attrs:
                print(f"        {indent}  Other attributes ({len(other_attrs)}):")
                for key, value in list(other_attrs.items())[:8]:  # Show first 8
                    value_str = str(value)
                    if len(value_str) > 60:
                        value_str = value_str[:60] + "..."
                    print(f"        {indent}    • {key}: {value_str}")

        print("\n" + "=" * 60)
        print("\n📈 Summary:")
        print(f"   • Trace: {trace.trace_id[:16]}...")
        print(f"   • Total Spans: {len(spans)}")
        print(f"   • Errors: {trace.error_count}")

except Exception as e:
    print(f"\n❌ Error querying traces: {e}")
    import traceback

    traceback.print_exc()
