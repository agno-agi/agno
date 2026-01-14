"""
Send traces from different agents to different Arize Phoenix projects.

1. Install dependencies: pip install arize-phoenix openai openinference-instrumentation-agno opentelemetry-sdk opentelemetry-exporter-otlp
2. Setup your Arize Phoenix account and get your API key: https://phoenix.arize.com/
3. Set your Arize Phoenix API key as an environment variable:
  - export PHOENIX_API_KEY=<your-key>
"""

import asyncio
import os

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from openinference.instrumentation import dangerously_using_project
from phoenix.otel import register
from pydantic import BaseModel

os.environ["PHOENIX_API_KEY"] = os.getenv("PHOENIX_API_KEY")
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = (
    "https://app.phoenix.arize.com/"  # Add the suffix for your organization
)

# Register a single tracer provider (project name here is the default)
tracer_provider = register(
    project_name="default",
    auto_instrument=True,
)


class StockPrice(BaseModel):
    stock_price: float


class SearchResult(BaseModel):
    summary: str
    sources: list[str]


# Agent 1 - Stock Price Agent
stock_agent = Agent(
    name="Stock Price Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[YFinanceTools()],
    db=InMemoryDb(),
    instructions="You are a stock price agent. Answer questions in the style of a stock analyst.",
    session_id="stock_session",
    output_schema=StockPrice,
)

# Agent 2 - Search Agent
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
    # Run stock_agent and send traces to "default" project
    with dangerously_using_project("default"):
        await stock_agent.aprint_response(
            "What is the current price of Tesla?", stream=True
        )

    # Run search_agent and send traces to "Testing-agno" project
    with dangerously_using_project("Testing-agno"):
        await search_agent.aprint_response(
            "What is the latest news about AI?", stream=True
        )


asyncio.run(main())
