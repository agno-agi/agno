"""
Scavio Tools
=============================

Demonstrates the Scavio toolkit: a unified Search API over Google, YouTube, Amazon,
Walmart, Reddit, TikTok, and Instagram.

Setup:
    pip install -U "agno[scavio]"  # requires scavio>=0.4.0 (Google Search uses the v2 API)
    export SCAVIO_API_KEY=***  # get a key at https://dashboard.scavio.dev
"""

from agno.agent import Agent
from agno.tools.scavio import ScavioTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: default ScavioTools (every provider enabled)
agent = Agent(tools=[ScavioTools()])

# Example 2: only the web providers (Google, YouTube, Reddit)
web_agent = Agent(
    tools=[
        ScavioTools(
            include_tools=[
                "search_google",
                "search_youtube",
                "get_youtube_video",
                "search_reddit",
                "get_reddit_post",
            ]
        )
    ]
)

# Example 3: only the commerce providers (Amazon, Walmart)
commerce_agent = Agent(
    tools=[
        ScavioTools(
            include_tools=[
                "search_amazon",
                "get_amazon_product",
                "search_walmart",
                "get_walmart_product",
            ]
        )
    ]
)

# Example 4: exclude a provider instead of listing includes
no_social_agent = Agent(
    tools=[
        ScavioTools(
            exclude_tools=[
                "get_tiktok_profile",
                "list_tiktok_posts",
                "get_tiktok_video",
            ]
        )
    ]
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    web_agent.print_response(
        "Search Google for the latest news on AI agent frameworks",
        markdown=True,
        stream=True,
    )

    web_agent.print_response(
        "What are people on Reddit saying about the Agno framework?",
        markdown=True,
        stream=True,
    )

    commerce_agent.print_response(
        "Compare prices for a 'mechanical keyboard' on Amazon and Walmart",
        markdown=True,
        stream=True,
    )
