"""
Cerebras Openai Basic
=====================

Cookbook example for `cerebras_openai/basic.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.cerebras import CerebrasOpenAI

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=CerebrasOpenAI(id="llama-4-scout-17b-16e-instruct"),
    markdown=True,
)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("write a two sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("write a two sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("write a two sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("write a two sentence horror story", stream=True))
