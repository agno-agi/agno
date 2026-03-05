"""
Anthropic Web Fetch
===================

Cookbook example for `anthropic/web_fetch.py`.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(id="claude-sonnet-4-6"),
    tools=[
        {
            "type": "web_fetch_20250910",
            "name": "web_fetch",
            "max_uses": 5,
        }
    ],
    markdown=True,
)

agent.print_response(
    "Tell me more about https://en.wikipedia.org/wiki/Glacier_National_Park_(U.S.)",
    stream=True,
)

# Show preserved server tool blocks
run_output = agent.get_last_run_output()
print("---" * 5, "Server Tool Blocks", "---" * 5)
for msg in run_output.messages or []:
    if msg.role != "assistant" or not msg.provider_data:
        continue
    for block in msg.provider_data.get("server_tool_blocks", []):
        block_type = block.get("type", "unknown")
        if block_type == "server_tool_use":
            print(f"  {block_type}: name={block.get('name')}, input={block.get('input')}")
        elif block_type == "web_fetch_tool_result":
            content = block.get("content", {})
            if isinstance(content, dict):
                print(f"  {block_type}: url={content.get('url', 'N/A')}")
            else:
                print(f"  {block_type}")
        else:
            print(f"  {block_type}")
print("---" * 20)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
