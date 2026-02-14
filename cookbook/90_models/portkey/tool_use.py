"""
Portkey Tool Use
================

Cookbook example for `portkey/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.portkey import Portkey
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Portkey(id="@first-integrati-707071/gpt-5-nano"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What are the latest developments in AI gateways?")

    # --- Sync + Streaming ---
    agent.print_response(
        "What are the latest developments in AI gateways?", stream=True
    )

    # --- Async ---
    asyncio.run(
        agent.aprint_response("What are the latest developments in AI gateways?")
    )

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "What are the latest developments in AI gateways?", stream=True
        )
    )
