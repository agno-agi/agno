from typing import Iterator  # noqa
from pydantic import BaseModel
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response


class StockAnalysis(BaseModel):
    symbol: str
    company_name: str
    analysis: str


stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    response_model=StockAnalysis,
    role="Searches the web for information on a stock.",
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
        )
    ],
)


class CompanyAnalysis(BaseModel):
    company_name: str
    analysis: str


company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    response_model=CompanyAnalysis,
    tools=[
        YFinanceTools(
            stock_price=False,
            company_info=True,
            company_news=True,
        )
    ],
)


team = Team(
    name="Stock Research Team",
    mode="route",
    model=OpenAIChat("gpt-4o"),
    members=[stock_searcher, company_info_agent],
    markdown=True,
    show_members_responses=True,
)

response = team.run("What is the current stock price of NVDA?")
assert isinstance(response.content, StockAnalysis)
pprint_run_response(response)

response = team.run("What is in the news about NVDA?")
assert isinstance(response.content, CompanyAnalysis)
pprint_run_response(response)
