"""
Scavio Tools
=============================

Demonstrates the Scavio toolkit: a unified Search API over Google, YouTube, Amazon,
Walmart, Reddit, TikTok, TikTok Shop, Instagram, X, and LinkedIn.

ScavioTools exposes 97 tools, one per live Scavio endpoint, so enable only the
providers an agent needs: 97 tool definitions in one prompt is a lot of context.

Setup:
    pip install agno scavio
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
            enable_google=True,
            enable_youtube=True,
            enable_reddit=True,
            enable_amazon=False,
            enable_walmart=False,
            enable_tiktok=False,
            enable_tiktok_shop=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
        )
    ]
)

# Example 3: only the commerce providers (Amazon, Walmart, TikTok Shop)
commerce_agent = Agent(
    tools=[
        ScavioTools(
            enable_google=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_amazon=True,
            enable_walmart=True,
            enable_tiktok=False,
            enable_tiktok_shop=True,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
        )
    ]
)

# Example 4: only the social providers (X, LinkedIn, Reddit)
social_agent = Agent(
    tools=[
        ScavioTools(
            enable_google=False,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_tiktok=False,
            enable_tiktok_shop=False,
            enable_instagram=False,
            enable_reddit=True,
            enable_x=True,
            enable_linkedin=True,
        )
    ]
)

# Example 5: Google only - the SERP plus its thirteen verticals (Maps, Shopping,
# Flights, Hotels, News, Trends, AI Mode)
google_agent = Agent(
    tools=[
        ScavioTools(
            enable_google=True,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_tiktok_shop=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
        )
    ]
)

# Example 6: enable every tool explicitly
all_agent = Agent(tools=[ScavioTools(all=True)])

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

    google_agent.print_response(
        "Find three highly rated ramen places in Austin, then check whether interest in "
        "'ramen' is rising or falling in Texas over the last 12 months",
        markdown=True,
        stream=True,
    )

    commerce_agent.print_response(
        "Compare prices for a 'mechanical keyboard' on Amazon, Walmart and TikTok Shop",
        markdown=True,
        stream=True,
    )

    commerce_agent.print_response(
        "For Amazon ASIN B09V3KXJPB, list every seller and tell me who holds the buy box",
        markdown=True,
        stream=True,
    )

    social_agent.print_response(
        "What are people on X and LinkedIn saying about AI agents this week?",
        markdown=True,
        stream=True,
    )
