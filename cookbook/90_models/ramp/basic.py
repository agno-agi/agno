"""
Router Basic
============

Cookbook example for `ramp/basic.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.ramp import RampRouter

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=RampRouter(id="gpt-5.6-luna"),
    markdown=True,
)

# The same model can be selected with a model string
agent_from_string = Agent(
    model="ramp:gpt-5.6-luna",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("write a two sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("write a two sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent_from_string.aprint_response("write a two sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(
        agent_from_string.aprint_response(
            "write a two sentence horror story", stream=True
        )
    )
