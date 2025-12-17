"""
This example demonstrates streaming responses from a team.

The team uses specialized agents with financial tools to provide real-time
stock information with streaming output.
"""

from typing import Iterator  # noqa
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools

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
    role="Searches the web for information on a stock.",
    tools=[
        YFinanceTools(
            include_tools=["get_company_info", "get_company_news"],
        )
    ],
)

# Create team with streaming capabilities
team = Team(
    name="Stock Research Team",
    model=OpenAIChat("o3-mini"),
    members=[stock_searcher, company_info_agent],
    markdown=True,
    show_members_responses=True,
)

# Test streaming response
team.print_response(
    "What is the current stock price of NVDA?",
    stream=True,
)

# You can also hide member responses for a specific call
team.print_response(
    "What is the latest news for TSLA?",
    stream=True,
    show_member_responses=False,  # Does not show member responses for this call only
)
