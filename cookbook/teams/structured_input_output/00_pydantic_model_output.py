from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.pprint import pprint_run_response
from pydantic import BaseModel


class StockAnalysis(BaseModel):
    symbol: str
    company_name: str
    analysis: str


class CompanyAnalysis(BaseModel):
    company_name: str
    analysis: str


stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    output_schema=StockAnalysis,
    role="Searches for information on stocks and provides price analysis.",
    tools=[DuckDuckGoTools()],
)

company_info_agent = Agent(
    name="Company Info Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches for information about companies and recent news.",
    output_schema=CompanyAnalysis,
    tools=[DuckDuckGoTools()],
)


class StockReport(BaseModel):
    symbol: str
    company_name: str
    analysis: str


team = Team(
    name="Stock Research Team",
    model=OpenAIChat("gpt-4o"),
    respond_directly=True,
    members=[stock_searcher, company_info_agent],
    output_schema=StockReport,
    markdown=True,
)

# The team leader should delegate the task to the stock_searcher
response = team.run("What is the current stock price of NVDA?")
assert isinstance(response.content, StockReport)
pprint_run_response(response)
