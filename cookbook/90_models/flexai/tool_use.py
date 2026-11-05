"""
FlexAI Tool Use
===============
Cookbook example for `flexai/tool_use.py`.
"""

import asyncio

from agno.agent import Agent
from agno.models.flexai import FlexAI
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=FlexAI(id="DeepSeek-V4-Flash-0731"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What's the latest news about AI?")

    # --- Sync + Streaming ---
    agent.print_response("What's the current weather in Tokyo?", stream=True)

    # --- Async ---
    asyncio.run(
        agent.aprint_response("What is the latest price about BTCUSDT on Binance?")
    )

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response(
            "Search for the latest developments in quantum computing and summarize them",
            stream=True,
        )
    )
