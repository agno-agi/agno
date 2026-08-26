"""
Volcengine Ark Basic
====================

The minimal Ark agent, run four ways: sync, sync + streaming, async, and
async + streaming. Start here to confirm your `ARK_API_KEY` works.

Get an API key:
    Create an API key in the Volcengine Ark console at
    https://console.volcengine.com/ark/region:cn-beijing/apiKey and export it:

        export ARK_API_KEY=***
"""

import asyncio

from agno.agent import Agent
from agno.models.volcengine import Ark

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Ark(id="doubao-seed-2-1-pro-260628"), markdown=True)

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
