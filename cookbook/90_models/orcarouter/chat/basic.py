"""
OrcaRouter Basic
================

Cookbook example for `orcarouter/chat/basic.py`.

OrcaRouter is an OpenAI-compatible model router. Use any model id from the catalog
(https://www.orcarouter.ai/models), or the virtual router `orcarouter/auto`.

You can also use the string syntax: `Agent(model="orcarouter:openai/gpt-4o-mini")`.
"""

import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.orcarouter import OrcaRouter

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=OrcaRouter(id="openai/gpt-4o-mini"), markdown=True)

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
