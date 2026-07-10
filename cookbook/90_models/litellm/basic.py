"""
Litellm Basic
=============

Cookbook example for `litellm/basic.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.litellm import LiteLLM

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

openai_agent = Agent(
    model=LiteLLM(
        id="huggingface/mistralai/Mistral-7B-Instruct-v0.2",
        top_p=0.95,
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    openai_agent.print_response("Whats happening in France?")

    # --- Sync + Streaming ---
    openai_agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    asyncio.run(openai_agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(
        openai_agent.aprint_response("Share a 2 sentence horror story", stream=True)
    )
