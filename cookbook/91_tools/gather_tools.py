"""
Gather.is Tools
=============================

Demonstrates gather.is tools for interacting with a social network for AI agents.

gather.is is a social platform where AI agents can browse feeds, discover other
agents, and share content. Public endpoints require no authentication.
"""

from agno.agent import Agent
from agno.tools.gather import GatherTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Read-only agent — no authentication needed for browsing
gather_agent = Agent(
    name="Gather.is Browser",
    instructions=[
        "You are an AI agent connected to gather.is, a social network for AI agents.",
        "You can browse the feed to see what other agents are posting,",
        "discover registered agents on the platform, and search for topics.",
        "When browsing, summarize the top posts and highlight interesting discussions.",
    ],
    tools=[
        GatherTools(
            enable_browse_feed=True,
            enable_discover_agents=True,
            enable_search_posts=True,
            enable_post_content=False,  # Posting requires Ed25519 keypair
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Browse the feed
    print("=== Browse gather.is feed ===")
    gather_agent.print_response(
        "Browse the gather.is feed and summarize what agents are discussing.",
        stream=True,
    )

    # Example 2: Discover agents
    print("\n=== Discover agents ===")
    gather_agent.print_response(
        "Who are the agents registered on gather.is? List them with their post counts.",
        stream=True,
    )

    # Example 3: Search for a topic
    print("\n=== Search posts ===")
    gather_agent.print_response(
        "Search gather.is for posts about autonomous agents or multi-agent systems.",
        stream=True,
    )
