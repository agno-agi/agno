"""
Groq Basic
==========

Cookbook example for `groq/basic.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.groq import Groq
import asyncio

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Groq(id="llama-3.3-70b-versatile"), markdown=True)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response on the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a breakfast recipe.", markdown=True))

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response("Share a breakfast recipe.", markdown=True, stream=True)
    )
