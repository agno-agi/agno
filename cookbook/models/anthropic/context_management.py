"""
Context Management

Demonstrates Claude's context management feature for automatic tool result clearing.
This reduces token usage in long-running conversations with extensive tool use.

Documentation: https://docs.claude.com/en/docs/build-with-claude/context-editing
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-5",
        default_headers={"anthropic-beta": "context-management-2025-06-27"},
        context_management={
            "edits": [
                {
                    "type": "clear_tool_uses_20250919",
                    "trigger": {"type": "tool_uses", "value": 2},
                    "keep": {"type": "tool_uses", "value": 1},
                }
            ]
        },
    ),
    instructions="You are a helpful assistant.",
    tools=[DuckDuckGoTools()],
    db=SqliteDb(db_file="tmp/context_management.db"),
    session_id="context-editing",
    add_history_to_context=True,
    markdown=True,
)

agent.print_response(
    "Search for AI regulation in US. Make multiple searches to find the latest information."
)

# Display context management metrics
print("\n" + "=" * 60)
print("CONTEXT MANAGEMENT SUMMARY")
print("=" * 60)
response = agent.get_last_run_output()
if response and response.metrics:
    print(f"\nInput tokens: {response.metrics.input_tokens:,}")

# Print context management stats from the last message
if response and response.messages:
    for message in reversed(response.messages):
        if message.provider_data and "context_management" in message.provider_data:
            edits = message.provider_data["context_management"].get("applied_edits", [])
            if edits:
                print(
                    f"\n✅ Saved: {edits[-1].get('cleared_input_tokens', 0):,} tokens"
                )
                print(f"   Cleared: {edits[-1].get('cleared_tool_uses', 0)} tool uses")
                break

print("\n" + "=" * 60)
