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
            stock_price=True,
            analyst_recommendations=True,
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
            stock_price=False,
            company_info=True,
            company_news=True,
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
    stream_intermediate_steps=True,
)
