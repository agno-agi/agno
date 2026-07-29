"""
You.com Tools
=============================

Demonstrates the YouTools toolkit which exposes the You.com Search API as a
first-class Agno tool.

Set ``YDC_API_KEY`` in your environment before running this example.
Get a key at https://you.com/platform/api-keys.

No API key? You.com also hosts a free MCP profile at
``https://api.you.com/mcp?profile=free`` (``you-search`` with 100 queries/day,
no key or sign-up required). To use it, plug that URL into Agno's MCPTools
instead of YouTools.
"""

from agno.agent import Agent
from agno.tools.youcom import YouTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Default search agent
agent = Agent(
    tools=[YouTools(show_results=True)],
    markdown=True,
)

# Example 2: Search with a domain allowlist and a larger result count
agent_filtered = Agent(
    tools=[
        YouTools(
            include_domains=["cnbc.com", "reuters.com", "bloomberg.com"],
            num_results=8,
            show_results=True,
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Search for the latest AAPL news", markdown=True)

    agent_filtered.print_response(
        "What did major financial outlets say about NVDA earnings this week?",
        markdown=True,
    )
