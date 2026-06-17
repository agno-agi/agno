"""
Avian Basic
===========

Basic example using the Avian provider.

1. Install dependencies: `uv pip install openai agno`
2. Export your API key: `export AVIAN_API_KEY=***`
3. Run: `python cookbook/90_models/avian/basic.py`
"""

import asyncio

from agno.agent import Agent, RunOutput  # noqa
from agno.models.avian import Avian  # noqa

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Avian(id="deepseek/deepseek-v3.2"),
    markdown=True,
)

# Get the response in a variable
# run: RunOutput = agent.run("Share a 2 sentence horror story")
# print(run.content)

# Print the response in the terminal

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
