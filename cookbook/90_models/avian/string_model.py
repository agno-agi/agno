"""
Avian String Model
==================

Example using the string model syntax: "avian:model-id"
"""

import asyncio

from agno.agent import Agent  # noqa

# ---------------------------------------------------------------------------
# Create Agent using string syntax
# ---------------------------------------------------------------------------

agent = Agent(
    model="avian:deepseek/deepseek-v3.2",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Share a 2 sentence horror story")

    # --- Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))
