"""
TogetherLink Basic
==================

Cookbook example for `togetherlink/basic.py`.

The default model id is "auto", which lets the TogetherLink gateway pick a fast or
frontier Together model per request. Pass any id from `togetherlink models` to pin one.
"""

import asyncio

from agno.agent import Agent
from agno.models.togetherlink import TogetherLink

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=TogetherLink(),
    markdown=True,
)

pinned_agent = Agent(
    model=TogetherLink(id="zai-org/GLM-5.3-Flash"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Write a two sentence horror story")

    # --- Sync + Streaming ---
    pinned_agent.print_response("Write a two sentence horror story", stream=True)

    # --- Async + Streaming ---
    asyncio.run(
        pinned_agent.aprint_response("Write a two sentence horror story", stream=True)
    )
