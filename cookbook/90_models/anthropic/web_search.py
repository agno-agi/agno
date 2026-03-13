"""
Anthropic Web Search
====================

Cookbook example for `anthropic/web_search.py`.
"""

from pprint import pprint

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(
        id="claude-sonnet-4-20250514",
    ),
    db=InMemoryDb(),
    tools=[
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }
    ],
    markdown=True,
)

agent.print_response("What's the latest with Anthropic?", stream=True)

# Show the web search metrics
run_output = agent.get_last_run_output()
print("---" * 5, "Web Search Metrics", "---" * 5)
pprint(run_output.metrics)
print("---" * 20)

# Show preserved server tool blocks
print("---" * 5, "Server Tool Blocks", "---" * 5)
for msg in run_output.messages or []:
    if msg.role != "assistant" or not msg.provider_data:
        continue
    for block in msg.provider_data.get("server_tool_blocks", []):
        block_type = block.get("type", "unknown")
        if block_type == "server_tool_use":
            print(f"  {block_type}: name={block.get('name')}, input={block.get('input')}")
        elif block_type == "web_search_tool_result":
            content = block.get("content", [])
            count = len(content) if isinstance(content, list) else 0
            print(f"  {block_type}: {count} search results")
        else:
            print(f"  {block_type}")
print("---" * 20)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
