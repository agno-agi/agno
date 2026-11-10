"""
Cometapi Tool Use
=================

Cookbook example for `cometapi/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.cometapi import CometAPI
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=CometAPI(id="gpt-5-mini"),
    tools=[WebSearchTools()],
    markdown=True,
)

# Print the response in the terminal

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What is the latest price about BTCUSDT on Binance?")

    # --- Sync + Streaming ---
    agent.print_response(
        "What's the current weather in Tokyo and what are some popular tourist attractions there?",
        stream=True,
    )

    # --- Async ---
    asyncio.run(agent.aprint_response("What's the latest news about AI?"))

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "Search for the latest developments in quantum computing and summarize them",
            stream=True,
        )
    )
