"""
Gemini Interactions - Google Search
====================================

Example using the built-in Google Search tool with the Interactions API.
"""

import asyncio

from agno.agent import Agent
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(
        id="gemini-3-flash-preview",
        search=True,
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What are the latest developments in quantum computing?")

    # --- Streaming ---
    asyncio.run(
        agent.aprint_response("What are the top news stories today?", stream=True)
    )
