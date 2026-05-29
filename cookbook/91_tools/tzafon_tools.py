"""
Tzafon Tools
=============================

Demonstrates the Tzafon (Lightcone) cloud-computer tools: an agent visits a website
and describes it from a screenshot it can actually see.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.tzafon import TzafonTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Tzafon Configuration
# -------------------------------
# TZAFON_API_KEY: Your API key from the Lightcone developer dashboard.
#   - Required for authentication
#   - Get your API key from https://lightcone.ai/developer

# The agent uses a vision-capable model to "see" the screenshots the toolkit
# returns, plus the TzafonTools to drive a Tzafon cloud browser.

agent = Agent(
    name="Tzafon Web Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[TzafonTools(kind="browser")],
    instructions=[
        "You browse the web using a Tzafon cloud browser.",
        "When given a URL:",
        "1. Navigate to the page.",
        "2. Take a screenshot so you can see the page.",
        "3. Describe what is on the page.",
        "4. Include the hosted screenshot URL in your answer.",
        "5. Close the session when you are done.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "Visit https://news.ycombinator.com and describe the top stories"
    )

    # ==================== Async Usage ====================
    # The same agent works for async - just use aprint_response, which routes to the
    # async tool variants automatically.
    #
    # import asyncio
    #
    #
    # async def main():
    #     await agent.aprint_response(
    #         "Visit https://news.ycombinator.com and describe the top stories"
    #     )
    #
    #
    # asyncio.run(main())
