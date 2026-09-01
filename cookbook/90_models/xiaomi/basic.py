"""
Xiaomi MiMo Basic
=================

The minimal MiMo agent, run four ways: sync, sync + streaming, async, and
async + streaming. Start here to confirm your `MIMO_API_KEY` works.

Get an API key:
    Sign in with a Xiaomi account (register at https://id.mi.com if you don't
    have one), then create a key in the console at https://platform.xiaomimimo.com
    under "API Keys", and export it:

        export MIMO_API_KEY=***
"""

import asyncio

from agno.agent import Agent
from agno.models.xiaomi import MiMo

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=MiMo(id="mimo-v2.5-pro"), markdown=True)

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
