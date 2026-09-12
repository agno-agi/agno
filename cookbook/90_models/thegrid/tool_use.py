"""
The Grid Tool Use
=================

Cookbook example for `thegrid/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.thegrid import TheGrid
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=TheGrid(id="agent-standard"),
    tools=[WebSearchTools()],
    markdown=True,
)

# The string form resolves through the provider registry:
#   agent = Agent(model="thegrid:agent-standard", tools=[WebSearchTools()])

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Whats happening in France?", stream=True)

    # --- Sync + Streaming ---
    agent.print_response("Whats happening in France?", stream=True)

    # --- Async ---
    asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))

    # --- Async + Streaming ---
    asyncio.run(agent.aprint_response("Whats happening in France?", stream=True))
