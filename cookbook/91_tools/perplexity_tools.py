"""
Perplexity Search Tools
=============================

Demonstrates Perplexity Search tools for web search.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.perplexity import PerplexitySearch

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Basic search with default settings
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[PerplexitySearch()],
    show_tool_calls=True,
    markdown=True,
)

# Example 2: Search with recency and domain filters
agent_filtered = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        PerplexitySearch(
            max_results=10,
            search_recency_filter="week",
            search_domain_filter=["cnbc.com", "reuters.com", "bloomberg.com"],
            show_results=True,
        )
    ],
    show_tool_calls=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What are the latest developments in AI agents?", stream=True)
