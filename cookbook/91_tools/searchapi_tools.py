"""
SearchAPI Tools
=============================

Demonstrates SearchAPI tools for real-time SERP data across Google web,
Google News, Google Images, and YouTube.

Requires: SEARCHAPI_API_KEY environment variable.
Get your key at https://www.searchapi.io/
"""

from agno.agent import Agent
from agno.tools.searchapi import SearchApiTools

# ---------------------------------------------------------------------------
# Create Agents
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

# Example 3: YouTube video search
youtube_agent = Agent(
    tools=[SearchApiTools(enable_search_google=False, enable_search_youtube=True)],
    description="You are a video-discovery agent that finds relevant YouTube tutorials, talks, and reviews.",
    instructions=[
        "Use YouTube search to find videos that match the user's request.",
        "For each result include the channel, video length, view count, and when it was published.",
        "Prefer recent, high-quality sources; skip low-view or clearly unrelated videos.",
    ],
)

# Example 4: All engines enabled
agent_all = Agent(
    tools=[SearchApiTools(all=True)],
    description="You are a comprehensive search agent with access to web, news, images, and YouTube.",
    instructions=[
        "Use the appropriate search engine based on the user's request.",
        "For general questions use Google, for recent events use News, for videos use YouTube.",
    ],
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "What are the latest developments in AI agents?",
        markdown=True,
        stream=True,
    )

    youtube_agent.print_response(
        "Find 3 recent YouTube videos explaining how to build an AI agent with Python.",
        markdown=True,
        stream=True,
    )
