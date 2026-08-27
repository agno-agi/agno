"""
Serply Tools
=============================

Demonstrates Serply tools for Google web, Google News, and Google Scholar search.

Requires: SERPLY_API_KEY environment variable.
Get your key at https://serply.io
"""

from agno.agent import Agent
from agno.tools.serply import SerplyTools

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Example 1: Google web search (default)
agent = Agent(
    tools=[SerplyTools()],
    description="You are a web search agent that finds accurate, up-to-date information.",
    instructions=[
        "Use Serply to find the most relevant results for the user's query.",
        "Summarize the top results clearly and cite the links.",
    ],
)

# Example 2: News search
news_agent = Agent(
    tools=[SerplyTools(search_web=False, search_news=True)],
    description="You are a news agent that finds the latest news on any topic.",
    instructions=[
        "Search Google News for recent articles on the given topic.",
        "Present the top headlines with their sources and publish dates.",
    ],
)

# Example 3: Scholar search
scholar_agent = Agent(
    tools=[SerplyTools(search_web=False, search_scholar=True)],
    description="You are a research assistant that finds academic papers.",
    instructions=[
        "Search Google Scholar for papers that match the user's request.",
        "For each paper include the authors, citation count, and a link to the PDF when available.",
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

    scholar_agent.print_response(
        "Find 3 recent papers on retrieval augmented generation.",
        markdown=True,
        stream=True,
    )
