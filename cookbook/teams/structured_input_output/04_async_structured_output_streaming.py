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
    model=OpenAIChat("gpt-4o"),
    output_schema=StockAnalysis,
    role="Searches the web for information on a stock.",
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
        )
    ],
)

# Company information agent with structured output
company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    output_schema=CompanyAnalysis,
    tools=[
        YFinanceTools(
            stock_price=False,
            company_info=True,
            company_news=True,
        )
    ],
)

# Create team with structured output streaming
team = Team(
    name="Stock Research Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    members=[stock_searcher, company_info_agent],
    output_schema=StockReport,
    markdown=True,
    show_members_responses=True,
)


async def test_structured_streaming():
    """Test async structured output streaming."""
    await team.aprint_response(
        "Give me a stock report for NVDA", stream=True, stream_intermediate_steps=True
    )

    # Verify the response is properly structured
    assert isinstance(team.run_response.content, StockReport)
    print(f"\n✅ Response type verified: {type(team.run_response.content)}")


async def test_structured_streaming_with_arun():
    """Test async structured output streaming using arun() method."""
    await apprint_run_response(
        team.arun(
            input="Give me a stock report for AAPL",
            stream=True,
            stream_intermediate_steps=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(test_structured_streaming())

    asyncio.run(test_structured_streaming_with_arun())
