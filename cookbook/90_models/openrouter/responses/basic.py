"""Basic example using OpenRouter with the Responses API.

OpenRouter's Responses API (beta) provides OpenAI-compatible access to multiple
AI models through a unified interface.

Requirements:
- Set OPENROUTER_API_KEY environment variable
"""

import asyncio

from agno.agent import Agent
from agno.models.openrouter import OpenRouterResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenRouterResponses(id="openai/gpt-oss-20b", reasoning={"enabled": True}),
    markdown=True,
)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
