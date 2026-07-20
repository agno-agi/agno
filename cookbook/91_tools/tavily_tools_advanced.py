"""
Tavily Tools - Advanced Search Parameters
=============================

Demonstrates scoping Tavily web search with the advanced parameters:
domain restriction, recency, topic, and country localization.
"""

from agno.agent import Agent
from agno.tools.tavily import TavilyTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Domain-restricted research, limited to the last month, US-localized
research_agent = Agent(
    tools=[
        TavilyTools(
            include_domains=[
                "arxiv.org",
                "github.com",
            ],  # restrict results to these domains
            exclude_domains=["reddit.com"],  # drop results from these domains
            time_range="month",  # only results from the last month
            country="united states",  # boost results from this country
        )
    ],
    markdown=True,
)

# Recent news from the last few days (days applies to the news topic only)
news_agent = Agent(
    tools=[
        TavilyTools(
            topic="news",  # general, news, or finance
            days=3,  # only news from the last 3 days
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    research_agent.print_response(
        "Find recent papers on mixture-of-experts language models"
    )

    news_agent.print_response("What are the latest developments in AI?")
