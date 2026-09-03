"""
DaoXE Basic
===========

Cookbook example for `daoxe/basic.py`.

Model IDs are scoped to your DaoXE account catalog. List `GET /v1/models` and
export the one you want as `DAOXE_MODEL` to override the default.
"""

import asyncio

from agno.agent import Agent
from agno.models.daoxe import DaoXE

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=DaoXE(),
    markdown=True,
)

# You can also use the string syntax:
# agent = Agent(model="daoxe:gpt-5.5", markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("write a two sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("write a two sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("write a two sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("write a two sentence horror story", stream=True))
