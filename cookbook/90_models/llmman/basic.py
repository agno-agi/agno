"""
Llmman Basic
============

Cookbook example for `llmman/basic.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.llmman import Llmman

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Llmman(id="gemma4"), markdown=True)

# The string syntax works too: Agent(model="llmman:gemma4", markdown=True)

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
