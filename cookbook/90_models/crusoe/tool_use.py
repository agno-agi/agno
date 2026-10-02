"""
Crusoe Tool Use
===============

Cookbook example for `crusoe/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.crusoe import Crusoe
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Crusoe(id="nvidia/Nemotron-3-Super-120B-A12B"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal

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
