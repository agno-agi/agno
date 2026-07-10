"""
Siliconflow Basic
=================

Cookbook example for `siliconflow/basic.py`.
"""

from agno.agent import Agent, RunOutput  # noqa
from agno.models.siliconflow import Siliconflow
import asyncio

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Siliconflow(id="openai/gpt-oss-120b"), markdown=True)

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

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story", stream=True))
