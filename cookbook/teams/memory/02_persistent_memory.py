"""
This recipe shows how to store agent sessions in a sqlite database.

Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/teams/memory/02_persistent_memory.py` to run the agent
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.perplexity.perplexity import Perplexity
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from utils import print_chat_history

stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools()],
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
)

web_searcher = Agent(
    name="Web Searcher",
    model=Perplexity(id="sonar-pro"),
    role="Searches the web for information on a company.",
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
)

team = Team(
    name="Stock Team",
    mode="coordinate",
    model=OpenAIChat("gpt-4o"),
    # Store team sessions in a database
    storage=SqliteAgentStorage(
        table_name="team_sessions", db_file="tmp/persistent_memory.db"
    ),
    members=[stock_searcher, web_searcher],
    instructions=[
        "You can search the stock market for information about a particular company's stock.",
        "You can also search the web for wider company information.",
    ],
    # Set add_history_to_messages=true to add the previous chat history to the messages sent to the Model.
    enable_team_history=True,
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
    # The session_id is used to identify the session in the database
    # You can resume any session by providing a session_id
    # session_id="xxxx-xxxx-xxxx-xxxx",
)


# -*- Create a run
team.print_response("What is the current price of Apple stock?", stream=True)
# -*- Print the chat history
print_chat_history(team)

# -*- Ask a follow up question that continues the conversation
team.print_response("What was that price again?", stream=True)
# -*- Print the chat history
print_chat_history(team)
