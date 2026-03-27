"""
Cache Tool Calls
=============================

Demonstrates cache tool calls.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools(), YFinanceTools(cache_results=True)],
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(
        agent.aprint_response(
            "What is the current stock price of AAPL and latest news on 'Apple'?",
            markdown=True,
        )
    )
