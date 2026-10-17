"""
DaoXE Tool Use
==============

Cookbook example for `daoxe/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.daoxe import DaoXE
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=DaoXE(),
    tools=[WebSearchTools()],
    markdown=True,
)

# You can also use the string syntax:
# agent = Agent(model="daoxe:gpt-5.5", tools=[WebSearchTools()], markdown=True)

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
