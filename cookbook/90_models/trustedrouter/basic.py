"""
TrustedRouter Basic
===================

Cookbook example for `trustedrouter/basic.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.trustedrouter import TrustedRouter

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=TrustedRouter(),
    markdown=True,
)

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
