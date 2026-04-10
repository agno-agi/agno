"""
Xquik Tools
=============================

Demonstrates X/Twitter search, user lookup, tweet reading, and trends
via the Xquik API. Only requires XQUIK_API_KEY (1 env var).

For write operations (posting, replying, DMs), use XTools instead.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.xquik import XquikTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

"""
1. Get an API key at https://xquik.com (Dashboard -> API Keys)
2. Set the environment variable:
   export XQUIK_API_KEY="xk_your_key_here"
"""

# Initialize the Xquik toolkit
xquik_tools = XquikTools()

# Create an agent with Xquik tools
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    instructions=[
        "Use your tools to search and read X (Twitter) content",
        "When presenting search results, highlight the most engaging posts",
        "Include engagement metrics when they add context",
        "Never post or interact — this toolkit is read-only",
    ],
    tools=[xquik_tools],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Search for posts about a topic
    agent.print_response(
        "Search X for what people are saying about AI agents", markdown=True
    )

    # # Look up a user profile
    # agent.print_response(
    #     "Get the profile info for @AgnoAgi on X", markdown=True
    # )

    # # Check trending topics
    # agent.print_response(
    #     "What's trending on X right now?", markdown=True
    # )

    # # Read a specific tweet
    # agent.print_response(
    #     "Read this tweet: 1234567890", markdown=True
    # )
