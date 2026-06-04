"""
Search API — Fast Web Lookup
============================

Quick web search for recent information.

USE CASES:
- Find recent news articles
- Quick factual lookups
- Gather sources for research
- Check current events

Search API is fast (1-5 seconds) but returns raw results.
Your agent synthesizes the answer from the snippets.

For deep research with citations, use Task API instead.

Prerequisites:
- pip install parallel-web
- export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# =============================================================================
# SEARCH CONFIGURATIONS
# =============================================================================

# General search
general_search = ParallelTools(
    max_results=10,
)

# Tech news — filtered sources
tech_search = ParallelTools(
    include_domains=["techcrunch.com", "wired.com", "arstechnica.com", "theverge.com"],
    max_results=10,
)

# Financial news
finance_search = ParallelTools(
    include_domains=["reuters.com", "bloomberg.com", "wsj.com", "ft.com"],
    max_results=10,
)

# Quick lookup — concise results
quick_search = ParallelTools(
    max_results=5,
    max_chars_per_result=300,
)

# =============================================================================
# SEARCH AGENTS
# =============================================================================

# General news agent
news_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[general_search],
    markdown=True,
)

# Tech news specialist
tech_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[tech_search],
    markdown=True,
    instructions="You search tech news for the latest developments in technology.",
)

# Financial news specialist
finance_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[finance_search],
    markdown=True,
    instructions="You search financial news for market updates and company news.",
)

# =============================================================================
# RUN
# =============================================================================
if __name__ == "__main__":
    # Quick news search
    news_agent.print_response(
        "What are the latest developments in AI agents?",
        stream=True,
    )
