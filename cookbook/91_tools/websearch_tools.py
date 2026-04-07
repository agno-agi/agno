"""
Websearch Tools
=============================

Demonstrates websearch tools.
"""

from agno.agent import Agent
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Basic web search with auto backend selection (default)
# Both web_search and search_news are enabled by default
agent = Agent(
    tools=[WebSearchTools()],
    description="You are a web search agent that helps users find information online.",
    instructions=["Search the web to find accurate and up-to-date information."],
)

# Example 2: Enable only news search
news_agent = Agent(
    tools=[WebSearchTools(enable_search=False, enable_news=True)],
    description="You are a news agent that helps users find the latest news.",
    instructions=[
        "Given a topic by the user, respond with the latest news about that topic."
    ],
)

# Example 3: Use DuckDuckGo backend explicitly
duckduckgo_agent = Agent(tools=[WebSearchTools(backend="duckduckgo")])

# Example 4: Use Google backend
google_agent = Agent(tools=[WebSearchTools(backend="google")])

# Example 5: Use Bing backend
bing_agent = Agent(tools=[WebSearchTools(backend="bing")])

# Example 6: Use Brave backend
brave_agent = Agent(tools=[WebSearchTools(backend="brave")])

# Example 7: Use with proxy and custom timeout
proxy_agent = Agent(
    tools=[WebSearchTools(backend="auto", proxy="socks5://localhost:9050", timeout=30)]
)

# Example 8: Use with fixed max results and modifier
modified_agent = Agent(
    tools=[
        WebSearchTools(
            backend="auto",
            modifier="site:github.com",  # Limit searches to GitHub
            fixed_max_results=3,
        )
    ]
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Run Example 1: Basic web search with auto backend
    print("\n" + "=" * 60)
    print("Example 1: Basic web search with auto backend")
    print("=" * 60)
    agent.print_response("What is the capital of France?", markdown=True)

    # Run Example 2: News-only agent
    print("\n" + "=" * 60)
    print("Example 2: News-only agent")
    print("=" * 60)
    news_agent.print_response("Find recent news about electric vehicles", markdown=True)

    # Run Example 3: DuckDuckGo backend
    print("\n" + "=" * 60)
    print("Example 3: DuckDuckGo backend")
    print("=" * 60)
    duckduckgo_agent.print_response("What is quantum computing?", markdown=True)

    # Run Example 4: Google backend
    print("\n" + "=" * 60)
    print("Example 4: Google backend")
    print("=" * 60)
    google_agent.print_response("What is machine learning?", markdown=True)

    # Run Example 5: Bing backend
    print("\n" + "=" * 60)
    print("Example 5: Bing backend")
    print("=" * 60)
    bing_agent.print_response("What is cloud computing?", markdown=True)

    # Run Example 6: Brave backend
    print("\n" + "=" * 60)
    print("Example 6: Brave backend")
    print("=" * 60)
    brave_agent.print_response("What is blockchain technology?", markdown=True)

    # Run Example 8: Modified search (GitHub only)
    print("\n" + "=" * 60)
    print("Example 8: Modified search (GitHub only)")
    print("=" * 60)
    modified_agent.print_response("Find Python web frameworks", markdown=True)
