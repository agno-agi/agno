"""
This example demonstrates asynchronous streaming responses from a team.

The team uses specialized agents with financial tools to provide real-time
stock information with async streaming output.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import apprint_run_response

# Stock price and analyst data agent
stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("o3-mini"),
    role="Searches the web for information on a stock.",
    tools=[
        YFinanceTools(
            include_tools=["get_current_stock_price", "get_analyst_recommendations"],
        )
    ],
)

# Company information agent
company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIChat("o3-mini"),
    role="Searches the web for information on a company.",
    tools=[
        YFinanceTools(
            include_tools=["get_company_info", "get_company_news"],
        )
    ],
)

# Create team with async streaming capabilities
team = Team(
    name="Stock Research Team",
    model=OpenAIChat("o3-mini"),
    members=[stock_searcher, company_info_agent],
    markdown=True,
    show_members_responses=True,
)


async def streaming_with_arun():
    """Demonstrate async streaming using arun() method."""
    await apprint_run_response(
        team.arun(input="What is the current stock price of NVDA?", stream=True)
    )


async def streaming_with_aprint_response():
    """Demonstrate async streaming using aprint_response() method."""
    await team.aprint_response("What is the current stock price of NVDA?", stream=True)


if __name__ == "__main__":
    asyncio.run(streaming_with_arun())

    # asyncio.run(streaming_with_aprint_response())
