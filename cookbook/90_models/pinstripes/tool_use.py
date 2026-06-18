"""
Pinstripes Tool Use
===================

Cookbook example for `pinstripes/tool_use.py`.

Set the PINSTRIPES_API_KEY environment variable before running:

    export PINSTRIPES_API_KEY=***
"""

import asyncio

from agno.agent import Agent
from agno.models.pinstripes import Pinstripes
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Pinstripes(id="ps/qwen3-35b"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Whats happening in France?")

    # --- Sync + Streaming ---
    agent.print_response("Whats happening in France?", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Whats happening in France?"))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
