"""
This recipe shows how to store personalized memories and summaries in a sqlite database.

Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/teams/memory/03_user_memories.py` to run the agent
"""

from agno.agent import Agent
from agno.memory.db.sqlite import SqliteMemoryDb
from agno.memory.team import TeamMemory
from agno.models.openai import OpenAIChat
from agno.models.perplexity.perplexity import Perplexity
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from utils import print_team_memory

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
    # The memories are personalized for this user
    user_id="john_billings",
    # Store the memories and summary in a table: agent_memory
    memory=TeamMemory(
        db=SqliteMemoryDb(
            table_name="team_memory",
            db_file="tmp/team_memory.db",
        ),
        # Create and store personalized memories for this user
        create_user_memories=True,
        # Update memories for the user after each run
        update_user_memories_after_run=True,
    ),
    members=[stock_searcher, web_searcher],
    instructions=[
        "You can search the stock market for information about a particular company's stock.",
        "You can also search the web for wider company information.",
    ],
    # Set enable_team_history=true to add the previous chat history to the messages sent to the Model.
    enable_team_history=True,
    num_of_interactions_from_history=5,
    show_tool_calls=True,
    markdown=True,
    debug_mode=True,
    show_members_responses=True,
    # The session_id is used to identify the session in the database
    # You can resume any session by providing a session_id
    # session_id="xxxx-xxxx-xxxx-xxxx",
)


# -*- Share personal information
team.print_response("My name is john billings and I live in nyc.", stream=True)
# -*- Print team memory
print_team_memory(team)

# -*- Share personal information
team.print_response("What is the price of apple stock?", stream=True)
# -*- Print team memory
print_team_memory(team)

# Ask about the conversation
team.print_response(
    "What have we been talking about, do you know my name?", stream=True
)
