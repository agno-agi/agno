"""
Cometapi Basic
==============

Cookbook example for `cometapi/basic.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.cometapi import CometAPI
import asyncio

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=CometAPI(id="gpt-5.2"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Explain quantum computing in simple terms")
# print(run.content)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Explain quantum computing in simple terms")

    # --- Sync + Streaming ---
    agent.print_response("Explain quantum computing in simple terms", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "Write a short poem about artificial intelligence", stream=True
        )
    )
