"""Example of how to cache the session in memory for faster access."""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="xxx")

# Setup the Agent and Team
agent = Agent(model=OpenAIChat(id="gpt-4o-mini"))
team = Team(
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[agent],
    db=db,
    # Activate session caching. The session will be cached in memory for faster access.
    cache_session=True,
)

# Running the Team
team.print_response("Tell me a new interesting fact about space")

# You can get the cached session:
session = team.get_session()
