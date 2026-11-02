"""
Otari Basic
===========

Cookbook example for Otari, an OpenAI-compatible LLM gateway.
"""

import asyncio

from agno.agent import Agent
from agno.models.otari import Otari

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Otari(id="openai:gpt-4o"), markdown=True)

# You can also select the provider by string, which resolves to the same class:
# agent = Agent(model="otari:openai:gpt-4o", markdown=True)

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
