"""
Sarvam Basic
============

The minimal Sarvam agent, run four ways: sync, sync + streaming, async, and
async + streaming. Start here to confirm your `SARVAM_API_KEY` works.

Get an API key:
    Sign in at https://dashboard.sarvam.ai, create a Token Factory API key,
    and export it:

        export SARVAM_API_KEY=***
"""

import asyncio

from agno.agent import Agent
from agno.models.sarvam import Sarvam

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Sarvam(id="sarvam-105b", reasoning_effort="none"), markdown=True)

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
