"""
Opper Basic
===========

Cookbook example for `opper/basic.py`.
"""

import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.opper import Opper

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Opper(
        id="claude-sonnet-4-6",
    ),
    markdown=True,
)

# The string syntax works too: Agent(model="opper:claude-sonnet-4-6", markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

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
