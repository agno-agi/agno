"""
The Grid Basic
==============

Cookbook example for `thegrid/basic.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.thegrid import TheGrid

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=TheGrid(id="text-standard"),
    markdown=True,
)

# The string form resolves through the provider registry:
#   agent = Agent(model="thegrid:text-standard")

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("write a two sentence horror story", stream=True)

    # --- Sync + Streaming ---
    agent.print_response("write a two sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("write a two sentence horror story", stream=True))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("write a two sentence horror story", stream=True))
