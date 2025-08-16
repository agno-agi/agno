from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# Set up SQLite database
db_url = "sqlite:///tmp/memory.db"
db = SqliteDb(db_url=db_url)

session_id = "sqlite_memories"
user_id = "sqlite_user"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Pass the database to the agent
    db=db,
    # Enable memory
    enable_user_memories=True,
    # Enable session summaries
    enable_session_summaries=True,
)

agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
    stream=True,
    user_id=user_id,
    session_id=session_id,
)

agent.print_response(
    "What are my hobbies?", stream=True, user_id=user_id, session_id=session_id
)
