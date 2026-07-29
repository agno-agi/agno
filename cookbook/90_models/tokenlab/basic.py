"""
TokenLab Basic
==============

Cookbook example for `tokenlab/basic.py`.
"""

import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.tokenlab import TokenLab

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=TokenLab(id="gpt-5.4-mini"),
    markdown=True,
)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence sci-fi story")
# print(run.content)

# Print the response in the terminal

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
