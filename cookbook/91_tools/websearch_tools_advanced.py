"""
WebSearch Tools - Advanced Configuration
=========================================

Demonstrates advanced WebSearchTools configuration with timelimit, region,
and backend parameters for customized search behavior across multiple
search engines.

Parameters:
    - timelimit: Filter results by time ("d" = day, "w" = week, "m" = month, "y" = year)
    - region: Localize results (e.g., "us-en", "uk-en", "de-de", "fr-fr", "ru-ru")
    - backend: Search backend ("auto", "duckduckgo", "google", "bing", "brave", "yandex", "yahoo")
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Example 1: Time-limited search with auto backend
# ---------------------------------------------------------------------------
# Filter results to specific time periods

# Past day - for breaking news
daily_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            timelimit="d",  # Results from past day
            backend="auto",
        )
    ],
    instructions=["Search for the most recent information from today."],
)

# Past week - for recent developments
weekly_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            timelimit="w",  # Results from past week
            backend="auto",
        )
    ],
    instructions=["Search for recent information from the past week."],
)

# Past month - for broader recent context
monthly_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            timelimit="m",  # Results from past month
            backend="auto",
        )
    ],
    instructions=["Search for information from the past month."],
)

# Past year - for yearly trends
yearly_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            timelimit="y",  # Results from past year
            backend="auto",
        )
    ],
    instructions=["Search for information from the past year."],
)

# ---------------------------------------------------------------------------
# Example 2: Region-specific searches
# ---------------------------------------------------------------------------
# Localize search results based on region

# US English
us_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            region="us-en",
            backend="auto",
        )
    ],
    instructions=["Provide US-localized search results."],
)

# UK English
uk_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            region="uk-en",
            backend="auto",
        )
    ],
    instructions=["Provide UK-localized search results."],
)

# German
de_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            region="de-de",
            backend="auto",
        )
    ],
    instructions=["Provide German-localized search results."],
)

# French
fr_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            region="fr-fr",
            backend="auto",
        )
    ],
    instructions=["Provide French-localized search results."],
)

# Russian
ru_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            region="ru-ru",
            backend="auto",
        )
    ],
    instructions=["Provide Russian-localized search results."],
)

# ---------------------------------------------------------------------------
# Example 3: Different backend options
# ---------------------------------------------------------------------------
# Use specific search engines as backends

# DuckDuckGo backend
duckduckgo_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            backend="duckduckgo",
            timelimit="w",
            region="us-en",
        )
    ],
)

# Google backend
google_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            backend="google",
            timelimit="w",
            region="us-en",
        )
    ],
)

# Bing backend
bing_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            backend="bing",
            timelimit="w",
            region="us-en",
        )
    ],
)

# Brave backend
brave_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            backend="brave",
            timelimit="w",
            region="us-en",
        )
    ],
)

# Yandex backend
yandex_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            backend="yandex",
            timelimit="w",
            region="ru-ru",  # Yandex works well with Russian region
        )
    ],
)

# Yahoo backend
yahoo_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            backend="yahoo",
            timelimit="w",
            region="us-en",
        )
    ],
)

# ---------------------------------------------------------------------------
# Example 4: Combined configuration - Research assistant
# ---------------------------------------------------------------------------
# Combine all parameters for a powerful research assistant

research_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            backend="auto",  # Auto-select best available backend
            timelimit="w",  # Focus on recent results
            region="us-en",  # US English results
            fixed_max_results=10,  # Get more results
            timeout=20,  # Longer timeout for thorough search
        )
    ],
    instructions=[
        "You are a research assistant that finds comprehensive, recent information.",
        "Always cite your sources and provide context for your findings.",
        "Focus on authoritative and reliable sources.",
    ],
)

# ---------------------------------------------------------------------------
# Example 5: News-focused agent with time and region filters
# ---------------------------------------------------------------------------

news_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        WebSearchTools(
            backend="auto",
            timelimit="d",  # Today's news only
            region="us-en",
            enable_search=False,  # Disable general search
            enable_news=True,  # Enable news search only
        )
    ],
    instructions=[
        "You are a news assistant that finds today's breaking news.",
        "Summarize the key points and provide source links.",
    ],
)

# ---------------------------------------------------------------------------
# Example 6: Multi-region comparison agent
# ---------------------------------------------------------------------------
# Create agents for different regions to compare perspectives


def create_regional_agent(region: str, region_name: str) -> Agent:
    """Create a region-specific search agent."""
    return Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[
            WebSearchTools(
                backend="auto",
                timelimit="w",
                region=region,
            )
        ],
        instructions=[
            f"You are a search assistant for {region_name}.",
            "Provide localized search results and perspectives.",
        ],
    )


# Create regional agents
us_regional = create_regional_agent("us-en", "United States")
uk_regional = create_regional_agent("uk-en", "United Kingdom")
de_regional = create_regional_agent("de-de", "Germany")

# ---------------------------------------------------------------------------
# Run Examples
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Time-limited search
    print("\n" + "=" * 60)
    print("Example 1: Weekly time-limited search")
    print("=" * 60)
    weekly_agent.print_response("What are the latest AI developments?", markdown=True)

    # Example 2: Region-specific search (US)
    print("\n" + "=" * 60)
    print("Example 2: US region search")
    print("=" * 60)
    us_agent.print_response("What are trending tech topics?", markdown=True)

    # Example 3: DuckDuckGo backend with filters
    print("\n" + "=" * 60)
    print("Example 3: DuckDuckGo backend with time and region filters")
    print("=" * 60)
    duckduckgo_agent.print_response("What is quantum computing?", markdown=True)

    # Example 4: Research assistant
    print("\n" + "=" * 60)
    print("Example 4: Research assistant (combined configuration)")
    print("=" * 60)
    research_agent.print_response(
        "Find recent research on large language models", markdown=True
    )

    # Example 5: News agent
    print("\n" + "=" * 60)
    print("Example 5: News-focused agent (daily news)")
    print("=" * 60)
    news_agent.print_response("What are today's top tech headlines?", markdown=True)

    # Example 6: Regional comparison
    print("\n" + "=" * 60)
    print("Example 6: US regional agent")
    print("=" * 60)
    us_regional.print_response("What is the economic outlook?", markdown=True)
