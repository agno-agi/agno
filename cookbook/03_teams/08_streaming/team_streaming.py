"""
Team Streaming
==============

Demonstrates sync and async streaming responses from a team.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import apprint_run_response

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Searches the web for information on a stock.",
    tools=[
        YFinanceTools(
            include_tools=["get_current_stock_price", "get_analyst_recommendations"],
        )
    ],
)

company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIResponses(id="gpt-5-mini"),
    role="Searches the web for information on a company.",
    tools=[
        YFinanceTools(
            include_tools=["get_company_info", "get_company_news"],
        )
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Stock Research Team",
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[stock_searcher, company_info_agent],
    markdown=True,
    show_members_responses=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def streaming_with_arun() -> None:
    await apprint_run_response(
        team.arun(input="What is the current stock price of NVDA?", stream=True)
    )


async def streaming_with_aprint_response() -> None:
    await team.aprint_response("What is the current stock price of NVDA?", stream=True)


if __name__ == "__main__":
    # Sync streaming
    team.print_response(
        "What is the current stock price of NVDA?",
        stream=True,
    )

    team.print_response(
        "What is the latest news for TSLA?",
        stream=True,
        show_member_responses=False,
    )

    # Async streaming
    asyncio.run(streaming_with_arun())
    # asyncio.run(streaming_with_aprint_response())
