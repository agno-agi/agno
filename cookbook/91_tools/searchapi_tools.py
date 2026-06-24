"""
SearchAPI Tools
=============================

Demonstrates SearchAPI tools for real-time SERP data.

Requires: SEARCHAPI_API_KEY environment variable.
Get your key at https://www.searchapi.io/
"""

from agno.agent import Agent
from agno.tools.searchapi import SearchApiTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Google web search (default)
agent = Agent(
    tools=[SearchApiTools()],
    description="You are a web search agent that finds accurate, up-to-date information.",
    instructions=[
        "Use SearchAPI to find the most relevant results for the user's query.",
        "Summarize the top results clearly.",
    ],
)

# Example 2: News search
news_agent = Agent(
    tools=[SearchApiTools(enable_search_google=False, enable_search_news=True)],
    description="You are a news agent that finds the latest news on any topic.",
    instructions=[
        "Search Google News for recent articles on the given topic.",
        "Present the top headlines with their sources and dates.",
    ],
)

# Example 3: All engines enabled
agent_all = Agent(
    tools=[SearchApiTools(all=True)],
    description="You are a comprehensive search agent with access to web, news, images, and YouTube.",
    instructions=[
        "Use the appropriate search engine based on the user's request.",
        "For general questions use Google, for recent events use News, for videos use YouTube.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What are the latest developments in AI agents?", markdown=True
    )
