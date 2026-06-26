"""
Scavio Tools
=============================

Demonstrates the Scavio toolkit: a unified Search API over Google, YouTube, Amazon,
Walmart, Reddit, TikTok, and Instagram.

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
            enable_instagram=False,
        )
    ]
)

# Example 3: only the commerce providers (Amazon, Walmart)
commerce_agent = Agent(
    tools=[
        ScavioTools(
            enable_google=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_amazon=True,
            enable_walmart=True,
            enable_tiktok=False,
            enable_instagram=False,
        )
    ]
)

# Example 4: enable every tool explicitly
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

    commerce_agent.print_response(
        "Compare prices for a 'mechanical keyboard' on Amazon and Walmart",
        markdown=True,
        stream=True,
    )
