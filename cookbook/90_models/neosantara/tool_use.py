"""
Neosantara Tool Use
===================

Cookbook example for `neosantara/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.neosantara import Neosantara
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Neosantara(id="grok-4.1-fast-non-reasoning"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response(
        "What is the current stock price of NVDA and what is its 52 week high?"
    )

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response("What is the current stock price of NVDA?", stream=True)
    )
