"""
Inception Basic
===============

Cookbook example for `inception/basic.py`.

Get an API key:
1. Create an account at https://platform.inceptionlabs.ai/
2. Create a key under Dashboard -> API Keys
3. export INCEPTION_API_KEY=***
"""

import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.inception import Inception

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Inception(id="mercury-2"), markdown=True)

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
