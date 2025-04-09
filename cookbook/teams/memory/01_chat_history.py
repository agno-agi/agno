from agno.agent import Agent
from agno.memory.v2.memory import Memory
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from pydantic import BaseModel
from rich.pretty import pprint
from utils import print_chat_history

# This memory is shared by all the agents in the team
memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"))


class StockAnalysis(BaseModel):
    symbol: str
    company_name: str
    analysis: str


stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools()],
    memory=memory,
)

web_searcher = Agent(
    name="Web Searcher",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    role="Searches the web for information on a company.",
    memory=memory,
)

session_id = "stock_team_session_1"
user_id = "john_doe@example.com"

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
    memory=memory,
    # Set enable_team_history=true to add the previous chat history to the messages sent to the Model.
    enable_team_history=True,
    # Only need to set this on the team and not on team members, otherwise it will be done multiple times on each agent
    create_user_memories=True,
    markdown=True,
    show_members_responses=True,
)

# -*- Create a run
team.print_response(
    "Write a report on the Apple stock.", session_id=session_id, user_id=user_id
)

# -*- Print the messages in the memory
session_run = memory.runs[session_id][-1]
print_chat_history(session_run)

# -*- Ask a follow up question that continues the conversation
team.print_response(
    "Pull up the previous report again.", session_id=session_id, user_id=user_id
)
# -*- Print the messages in the memory
session_run = memory.runs[session_id][-1]
print_chat_history(session_run)
