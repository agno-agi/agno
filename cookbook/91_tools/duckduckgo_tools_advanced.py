"""
DuckDuckGo Tools - Advanced Configuration
==========================================

Demonstrates advanced DuckDuckGoTools configuration with timelimit, region,
and backend parameters for customized search behavior.

Parameters:
    - timelimit: Filter results by time ("d" = day, "w" = week, "m" = month, "y" = year)
    - region: Localize results (e.g., "us-en", "uk-en", "de-de", "fr-fr", "ru-ru")
    - backend: Search backend ("api", "html", "lite")
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Example 1: Time-limited search (results from past week)
# ---------------------------------------------------------------------------
# Useful for finding recent news, updates, or time-sensitive information

weekly_search_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(
            timelimit="w",  # Results from past week only
            enable_search=True,
            enable_news=True,
        )
    ],
    instructions=["Search for recent information from the past week."],
)

# ---------------------------------------------------------------------------
# Example 2: Region-specific search (US English results)
# ---------------------------------------------------------------------------
# Useful for localized results based on user's region

us_region_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(
            region="us-en",  # US English results
            enable_search=True,
            enable_news=True,
        )
    ],
    instructions=["Search for information with US-localized results."],
)

# ---------------------------------------------------------------------------
# Example 3: Different backend options
# ---------------------------------------------------------------------------
# The backend parameter controls how DuckDuckGo is queried

# API backend - uses DuckDuckGo's API
api_backend_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(
            backend="api",
            enable_search=True,
            enable_news=True,
        )
    ],
)

# HTML backend - parses HTML results
html_backend_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(
            backend="html",
            enable_search=True,
            enable_news=True,
        )
    ],
)

# Lite backend - lightweight parsing
lite_backend_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(
            backend="lite",
            enable_search=True,
            enable_news=True,
        )
    ],
)

# ---------------------------------------------------------------------------
# Example 4: Combined configuration - Full customization
# ---------------------------------------------------------------------------
# Combine all parameters for maximum control over search behavior

fully_configured_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(
            timelimit="w",  # Results from past week
            region="us-en",  # US English results
            backend="api",  # Use API backend
            enable_search=True,
            enable_news=True,
            fixed_max_results=10,  # Limit to 10 results
            timeout=15,  # 15 second timeout
        )
    ],
    instructions=[
        "You are a research assistant that finds recent US news and information.",
        "Always provide sources for your findings.",
    ],
)

# ---------------------------------------------------------------------------
# Example 5: European region search with monthly timelimit
# ---------------------------------------------------------------------------

eu_monthly_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(
            timelimit="m",  # Results from past month
            region="de-de",  # German results
            enable_search=True,
            enable_news=True,
        )
    ],
    instructions=["Search for information with German-localized results."],
)

# ---------------------------------------------------------------------------
# Example 6: Daily news search
# ---------------------------------------------------------------------------
# Perfect for finding breaking news and today's updates

daily_news_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(
            timelimit="d",  # Results from past day only
            enable_search=False,  # Disable web search
            enable_news=True,  # Enable news only
        )
    ],
    instructions=[
        "You are a news assistant that finds today's breaking news.",
        "Focus on the most recent and relevant stories.",
    ],
)

# ---------------------------------------------------------------------------
# Run Examples
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Weekly search
    print("\n" + "=" * 60)
    print("Example 1: Time-limited search (past week)")
    print("=" * 60)
    weekly_search_agent.print_response(
        "What are the latest developments in AI?", markdown=True
    )

    # Example 2: US region search
    print("\n" + "=" * 60)
    print("Example 2: Region-specific search (US English)")
    print("=" * 60)
    us_region_agent.print_response("What are the trending tech topics?", markdown=True)

    # Example 3: API backend
    print("\n" + "=" * 60)
    print("Example 3: API backend")
    print("=" * 60)
    api_backend_agent.print_response("What is quantum computing?", markdown=True)

    # Example 4: Fully configured agent
    print("\n" + "=" * 60)
    print("Example 4: Fully configured agent (weekly, US, API backend)")
    print("=" * 60)
    fully_configured_agent.print_response(
        "Find recent news about renewable energy in the US", markdown=True
    )

    # Example 5: European region with monthly timelimit
    print("\n" + "=" * 60)
    print("Example 5: European region (German) with monthly timelimit")
    print("=" * 60)
    eu_monthly_agent.print_response(
        "What are the latest technology trends?", markdown=True
    )

    # Example 6: Daily news
    print("\n" + "=" * 60)
    print("Example 6: Daily news search")
    print("=" * 60)
    daily_news_agent.print_response(
        "What are today's top headlines in technology?", markdown=True
    )
