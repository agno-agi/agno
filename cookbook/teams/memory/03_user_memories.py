"""
This recipe shows how to store personalized memories and summaries in a sqlite database.

Steps:
1. Run: `pip install openai sqlalchemy agno` to install dependencies
2. Run: `python cookbook/teams/memory/03_user_memories.py` to run the agent
"""

from agno.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from agno.models.perplexity.perplexity import Perplexity
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.team.team import Team
from agno.tools.yfinance import YFinanceTools
from utils import print_chat_history, print_team_memory

# This memory is shared by all the agents in the team
memory_db = SqliteMemoryDb(table_name="memory", db_file="tmp/memory.db")

memory = Memory(model=Gemini(id="gemini-2.0-flash-exp"), db=memory_db)

# Reset the memory for this example
memory.clear()


stock_searcher = Agent(
    name="Stock Searcher",
    model=OpenAIChat("gpt-4o"),
    role="Searches the web for information on a stock.",
    tools=[YFinanceTools(cache_results=True)],
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
    memory=memory,
)

web_searcher = Agent(
    name="Web Searcher",
    model=Perplexity(id="sonar-pro"),
    role="Searches the web for information on a company.",
    storage=SqliteAgentStorage(
        table_name="agent_sessions", db_file="tmp/persistent_memory.db"
    ),
    memory=memory,
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
    memory=memory,
    members=[stock_searcher, web_searcher],
    instructions=[
        "You can search the stock market for information about a particular company's stock.",
        "You can also search the web for wider company information.",
    ],
    # Set enable_team_history=true to add the previous chat history to the messages sent to the Model.
    enable_team_history=True,
    num_of_interactions_from_history=5,
    # Create and store personalized memories for this user
    enable_user_memories=True,
    show_tool_calls=True,
    markdown=True,
    show_members_responses=True,
)

session_id = "stock_team_session_1"
user_id = "john_billings"

# -*- Share personal information
team.print_response(
    "My name is john billings and I live in nyc.",
    stream=True,
    session_id=session_id,
    user_id=user_id,
)

session_run = memory.runs[session_id][-1]
# -*- Print chat history
print_chat_history(session_run)
# -*- Print team memory
print_team_memory(user_id, memory.get_user_memories(user_id))

# -*- Share personal information
team.print_response(
    "What is the price of apple stock?",
    stream=True,
    session_id=session_id,
    user_id=user_id,
)

session_run = memory.runs[session_id][-1]
# -*- Print chat history
print_chat_history(session_run)
# -*- Print team memory
print_team_memory(user_id, memory.get_user_memories(user_id))

# Ask about the conversation
team.print_response(
    "What have we been talking about, do you know my name?", stream=True
)

session_run = memory.runs[session_id][-1]
# -*- Print chat history
print_chat_history(session_run)
# -*- Print team memory (you can also get the user memories from the team)
print_team_memory(user_id, team.get_user_memories(user_id))
