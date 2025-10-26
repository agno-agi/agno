"""
This example demonstrates async structured output streaming from a team.

The team uses Pydantic models to ensure structured responses while streaming,
providing both real-time output and validated data structures asynchronously.
"""

import asyncio
from typing import Iterator  # noqa

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import apprint_run_response
from pydantic import BaseModel


class StockAnalysis(BaseModel):
    """Stock analysis data structure."""

    symbol: str
    company_name: str
    analysis: str


class CompanyAnalysis(BaseModel):
    """Company analysis data structure."""

    company_name: str
    analysis: str


class StockReport(BaseModel):
    """Final stock report data structure."""

    symbol: str
    company_name: str
    analysis: str


# Stock price and analyst data agent with structured output
stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("o3-mini"),
    output_schema=StockAnalysis,
    role="Searches the web for information on a stock.",
    tools=[
        YFinanceTools(
            include_tools=["get_current_stock_price", "get_analyst_recommendations"],
        )
    ],
)

# Company information agent with structured output
company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIChat("o3-mini"),
    role="Searches the web for information on a stock.",
    output_schema=CompanyAnalysis,
    tools=[
        YFinanceTools(
            include_tools=["get_company_info", "get_company_news"],
        )
    ],
)

# Create team with structured output streaming
team = Team(
    name="Stock Research Team",
    model=OpenAIChat("o3-mini"),
    members=[stock_searcher, company_info_agent],
    output_schema=StockReport,
    markdown=True,
    show_members_responses=True,
)


async def test_structured_streaming():
    """Test async structured output streaming."""
    # Run with streaming and consume the async generator to get the final response
    async_stream = team.arun(
        "Give me a stock report for NVDA", stream=True, stream_events=True
    )

    # Consume the async streaming events and get the final response
    run_response = None
    async for event_or_response in async_stream:
        # The last item in the stream is the final TeamRunOutput
        run_response = event_or_response

    assert isinstance(run_response.content, StockReport)
    print(f"✅ Stock Symbol: {run_response.content.symbol}")
    print(f"✅ Company Name: {run_response.content.company_name}")


async def test_structured_streaming_with_arun():
    """Test async structured output streaming using arun() method."""
    await apprint_run_response(
        team.arun(
            input="Give me a stock report for AAPL",
            stream=True,
            stream_events=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(test_structured_streaming())

    asyncio.run(test_structured_streaming_with_arun())
