"""
Hubris Basic
============

Cookbook example for `hubris/basic.py`.
Refer to cookbook/90_models/hubris/README.md for installation steps.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.hubris import Hubris

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Hubris(id="anthropic/claude-sonnet-5"), markdown=True)

# The string syntax works too: Agent(model="hubris:anthropic/claude-sonnet-5", markdown=True)

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
