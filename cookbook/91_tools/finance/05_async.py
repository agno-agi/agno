"""
Async FinanceTools
==================
Every FinanceTools tool has an async variant registered under the same name,
so `agent.arun()` / `agent.aprint_response()` use them automatically. Providers
with a native async client (financialdatasets.ai via httpx) run without a
thread; sync-only providers (yfinance) run in a worker thread.

This example fans out three tickers concurrently with one agent.
"""

import asyncio

from agno.agent import Agent
from agno.tools.finance import FinanceTools

# ---------------------------------------------------------------------------
# Create the Agent (reused across all runs - never create agents in a loop)
# ---------------------------------------------------------------------------
agent = Agent(
    name="Finance Agent",
    model="openai:gpt-5.6",
    tools=[FinanceTools()],
    instructions="Answer in three bullets: price and day change, valuation, one notable headline.",
    markdown=True,
)


async def main() -> None:
    tickers = ["NVDA", "AMD", "AVGO"]
    outputs = await asyncio.gather(
        *(agent.arun(f"Quick take on {ticker}") for ticker in tickers)
    )
    for ticker, output in zip(tickers, outputs):
        print(f"\n===== {ticker} =====\n{output.content}")


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
