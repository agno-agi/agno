"""Example of how to cache the session in memory for faster access."""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="xxx")

# Setup the agent
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    session_id="session_storage",
    add_history_to_context=True,
    # Activate session caching. The session will be cached in memory for faster access.
    cache_session=True,
)

# Running the Agent
agent.print_response("Tell me a new interesting fact about space")

# You can get the cached session:
session = agent.get_session()
