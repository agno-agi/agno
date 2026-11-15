"""
Crusoe Basic
============
Cookbook example for Crusoe, OpenAILike model provider.
"""

import asyncio

from agno.agent import Agent
from agno.models.crusoe import Crusoe

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Crusoe(id="openai/gpt-oss-120b"), markdown=True)

string_agent = Agent(model="crusoe:openai/gpt-oss-120b", markdown=True)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Explain quantum computing in simple terms")

    # --- Sync + Streaming ---
    string_agent.print_response(
        "Explain quantum computing in simple terms", stream=True
    )

    # --- Async ---
    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "Write a short poem about artificial intelligence", stream=True
        )
    )
