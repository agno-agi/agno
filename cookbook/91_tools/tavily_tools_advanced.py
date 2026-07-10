"""
Tavily Tools - Advanced Search Parameters
=============================

Demonstrates scoping Tavily web search with domain, recency, topic,
and country filters.
"""

from agno.agent import Agent
from agno.tools.tavily import TavilyTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: restrict search to trusted domains
research_agent = Agent(
    tools=[
        TavilyTools(
            include_domains=["arxiv.org", "github.com"],
            exclude_domains=["reddit.com"],
        )
    ]
)

# Example 2: recent news only
news_agent = Agent(
    tools=[
        TavilyTools(
            topic="news",
            time_range="week",
        )
    ]
)

# Example 3: date-window search with localized results
# (country applies to the default general topic only)
localized_agent = Agent(
    tools=[
        TavilyTools(
            start_date="2026-01-01",
            end_date="2026-06-30",
            country="united states",
        )
    ]
)

# Example 4: let Tavily auto-tune remaining search parameters
# (explicitly set values like search_depth take precedence)
auto_agent = Agent(
    tools=[
        TavilyTools(
            auto_parameters=True,
            chunks_per_source=3,
        )
    ]
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    research_agent.print_response("Find recent papers on mixture-of-experts language models", markdown=True)

    news_agent.print_response("What happened in AI this week?", markdown=True)

    localized_agent.print_response("Summarize major US tech earnings from the first half of 2026", markdown=True)
