"""
This recipe shows how to store agent sessions in a sqlite database and use chat history.

Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/teams/memory/02_persistent_chat_history.py` to run the agent
"""

from agno.agent import Agent
from agno.memory.v2.memory import Memory
from agno.models.anthropic.claude import Claude
from agno.models.perplexity.perplexity import Perplexity
from agno.storage.sqlite import SqliteStorage
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from utils import print_chat_history

memory = Memory()

stock_searcher = Agent(
    name="Stock Searcher",
    model=Claude(id="claude-3-5-sonnet-20241022"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools(cache_results=True)],
    storage=SqliteStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
    memory=memory,
)

web_searcher = Agent(
    name="Web Searcher",
    model=Perplexity(id="sonar-pro"),
    role="Searches the web for information on a company.",
    storage=SqliteStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
    memory=memory,
)

team = Team(
    name="Stock Team",
    mode="coordinate",
    model=Claude(id="claude-3-5-sonnet-20241022"),
    # Store team sessions in a database
    storage=SqliteStorage(
        table_name="team_sessions", db_file="tmp/persistent_memory.db"
    ),
    members=[stock_searcher, web_searcher],
    instructions=[
        "You can search the stock market for information about a particular company's stock.",
        "You can also search the web for wider company information.",
    ],
    # Set enable_team_history=true to add the previous chat history to the messages sent to the Model.
    enable_team_history=True,
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
    memory=memory,
)

session_id = "stock_team_session_1"

# -*- Create a run
team.print_response(
    "What is the current price of Apple stock?", stream=True, session_id=session_id
)

# -*- Print the chat history
session_run = memory.runs[session_id][-1]
print_chat_history(session_run)

# -*- Ask a follow up question that continues the conversation
team.print_response("What was that price again?", stream=True, session_id=session_id)

# -*- Print the chat history
session_run = memory.runs[session_id][-1]
print_chat_history(session_run)
