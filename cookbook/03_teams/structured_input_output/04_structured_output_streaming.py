from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from pydantic import BaseModel


class StockAnalysis(BaseModel):
    symbol: str
    company_name: str
    analysis: str


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


class CompanyAnalysis(BaseModel):
    company_name: str
    analysis: str


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


class StockReport(BaseModel):
    symbol: str
    company_name: str
    analysis: str


team = Team(
    name="Stock Research Team",
    model=OpenAIChat("o3-mini"),
    members=[stock_searcher, company_info_agent],
    output_schema=StockReport,
    markdown=True,
    show_members_responses=True,
)

# Run with streaming and consume the generator to get the final response
stream_generator = team.run(
    "Give me a stock report for NVDA",
    stream=True,
    stream_events=True,
)

# Consume the streaming events and get the final response
run_response = None
for event_or_response in stream_generator:
    # The last item in the stream is the final TeamRunOutput
    run_response = event_or_response

assert isinstance(run_response.content, StockReport)
print(
    f"✅ Response content is correctly typed as StockReport: {type(run_response.content)}"
)
print(f"✅ Stock Symbol: {run_response.content.symbol}")
print(f"✅ Company Name: {run_response.content.company_name}")
