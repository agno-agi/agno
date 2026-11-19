"""
Cheaper Inference Basic
=======================

Cookbook example for `cheaperinference/basic.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.cheaperinference import CheaperInference

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=CheaperInference(id="gpt-5.4-mini"), markdown=True)

# You can also select the provider by string, which resolves to the same class:
# agent = Agent(model="cheaperinference:gpt-5.4-mini", markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story.")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story.", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story."))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story.", stream=True))
