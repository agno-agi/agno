"""
This example demonstrates how to capture team responses as variables.

Shows how to get structured responses from teams and validate them using
Pydantic models for different types of queries.
"""

from typing import Iterator  # noqa
from pydantic import BaseModel
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from agno.utils.pprint import pprint_run_response


class StockAnalysis(BaseModel):
    """Stock analysis data structure."""

    symbol: str
    company_name: str
    analysis: str


class CompanyAnalysis(BaseModel):
    """Company analysis data structure."""

    company_name: str
    analysis: str


# Stock price analysis agent
stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("o3-mini"),
    output_schema=StockAnalysis,
    role="Searches for stock price and analyst information",
    tools=[
        YFinanceTools(
            include_tools=["get_current_stock_price", "get_analyst_recommendations"],
        )
    ],
    instructions=[
        "Provide detailed stock analysis with price information",
        "Include analyst recommendations when available",
    ],
)

# Company news and information agent
company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIChat("o3-mini"),
    role="Searches for company news and information",
    output_schema=CompanyAnalysis,
    tools=[
        YFinanceTools(
            include_tools=["get_company_info", "get_company_news"],
        )
    ],
    instructions=[
        "Focus on company news and business information",
        "Provide comprehensive analysis of company developments",
    ],
)

# Create routing team
team = Team(
    name="Stock Research Team",
    model=OpenAIChat("o3-mini"),
    respond_directly=True,
    members=[stock_searcher, company_info_agent],
    markdown=True,
    show_members_responses=True,
    instructions=[
        "Route stock price questions to the Stock Searcher",
        "Route company news and info questions to the Company Info Searcher",
    ],
)

# Example 1: Get stock price analysis as a variable
print("=" * 50)
print("STOCK PRICE ANALYSIS")
print("=" * 50)

stock_response = team.run("What is the current stock price of NVDA?")
assert isinstance(stock_response.content, StockAnalysis)
print(f"Response type: {type(stock_response.content)}")
print(f"Symbol: {stock_response.content.symbol}")
print(f"Company: {stock_response.content.company_name}")
print(f"Analysis: {stock_response.content.analysis}")
pprint_run_response(stock_response)

# Example 2: Get company news analysis as a variable
print("\n" + "=" * 50)
print("COMPANY NEWS ANALYSIS")
print("=" * 50)

news_response = team.run("What is in the news about NVDA?")
assert isinstance(news_response.content, CompanyAnalysis)
print(f"Response type: {type(news_response.content)}")
print(f"Company: {news_response.content.company_name}")
print(f"Analysis: {news_response.content.analysis}")
pprint_run_response(news_response)

# Example 3: Process multiple responses
print("\n" + "=" * 50)
print("BATCH PROCESSING")
print("=" * 50)

companies = ["AAPL", "GOOGL", "MSFT"]
responses = []

for company in companies:
    response = team.run(f"Analyze {company} stock")
    responses.append(response)
    print(f"Processed {company}: {type(response.content).__name__}")

print(f"Total responses processed: {len(responses)}")
