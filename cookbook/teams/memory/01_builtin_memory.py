from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from pydantic import BaseModel
from rich.pretty import pprint


class StockAnalysis(BaseModel):
    symbol: str
    company_name: str
    analysis: str


stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools()],
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    role="Searches the web for information on a company.",
)


team = Team(
    name="Stock Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    members=[stock_searcher, web_searcher],
    instructions=[
        "First, search the stock market for information about a particular company's stock.",
        "Then, ask the web searcher to search for wider company information.",
    ],
    response_model=StockAnalysis,
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
)

# -*- Create a run
team.print_response("Write a report on the Apple stock.", stream=True)

# -*- Print the messages in the memory
pprint([m.model_dump(include={"role", "content"}) for m in team.memory.messages])

# -*- Ask a follow up question that continues the conversation
team.print_response("Pull up the previous report again.", stream=True)
# -*- Print the messages in the memory
pprint([m.model_dump(include={"role", "content"}) for m in team.memory.messages])
