"""
Example: Send traces from different agents to different Arize Phoenix projects.
This example demonstrates the simple user experience for routing traces
to different Phoenix projects using Agno's built-in Phoenix integration.
1. Install dependencies: pip install arize-phoenix openai openinference-instrumentation-agno opentelemetry-sdk opentelemetry-exporter-otlp
2. Setup your Arize Phoenix account and get your API key: https://phoenix.arize.com/
3. Set environment variables:
   - export PHOENIX_API_KEY=<your-key>
   - export PHOENIX_COLLECTOR_ENDPOINT=https://app.phoenix.arize.com  (or your Phoenix instance)
"""

import asyncio
import os

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.tracing.phoenix import setup_phoenix, using_project
from pydantic import BaseModel

# Optional: Set endpoint if using Phoenix Cloud with organization space
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = "https://app.phoenix.arize.com/"


class StockPrice(BaseModel):
    stock_price: float


class SearchResult(BaseModel):
    summary: str
    sources: list[str]


# Set up Phoenix with project routing (one line!)
setup_phoenix(default_project="default")

# Create agents (they don't need to know about projects)
stock_agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    db=InMemoryDb(),
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    session_id="stock_session",
    output_schema=StockPrice,
)

search_agent = Agent(
    name="Search Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    db=InMemoryDb(),
    instructions="You are a search agent. Find and summarize information from the web.",
    session_id="search_session",
    output_schema=SearchResult,
)


async def main():
    # Route traces to specific projects using context manager
    print("Running Stock Price Agent (traces -> 'default' project)...")
    with using_project("default"):
        await stock_agent.aprint_response(
            "What is the current price of Tesla?", stream=True
        )

    print("\nRunning Search Agent (traces -> 'Testing-agno' project)...")
    with using_project("Testing-agno"):
        await search_agent.aprint_response(
            "What is the latest news about AI?", stream=True
        )


if __name__ == "__main__":
    asyncio.run(main())
	