"""
Heabsy Basic
============

Cookbook example for Heabsy, OpenAILike model provider.
"""

import asyncio

from agno.agent import Agent
from agno.models.heabsy import Heabsy

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Heabsy(id="qwen38"), markdown=True)

# You can also select the provider by string, which resolves to the same class:
# agent = Agent(model="heabsy:qwen38", markdown=True)

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
