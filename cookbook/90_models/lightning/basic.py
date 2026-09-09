"""
Lightning Basic
===============

Cookbook example for `lightning/basic.py`.
"""

import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.lightning import Lightning

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Lightning(id="openai/gpt-5-nano"),
    markdown=True,
)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence sci-fi story")
# print(run.content)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence sci-fi story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence sci-fi story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence sci-fi story"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Share a 2 sentence sci-fi story", stream=True))
