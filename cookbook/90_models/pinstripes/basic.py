"""
Pinstripes Basic
================

Cookbook example for `pinstripes/basic.py`.

Set the PINSTRIPES_API_KEY environment variable before running:

    export PINSTRIPES_API_KEY=***

Available models:
    - ps/deepseek-v4-flash   ($0.10/M tokens)
    - ps/glm-4.5-air         ($0.125/M tokens)
    - ps/qwen3-35b           ($0.14/M tokens)
    - ps/minimax-m2.7        ($0.255/M tokens)
"""

import asyncio

from agno.agent import Agent
from agno.models.pinstripes import Pinstripes

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Pinstripes(id="ps/deepseek-v4-flash"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
