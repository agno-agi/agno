"""Example of how to cache the team session in memory for faster access."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="sessions")

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
    name="Research Assistant",
)

# Setup the team
team = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[agent],
    db=db,
    session_id="team_session_cache",
    add_history_to_context=True,
    # Activate session caching. The session will be cached in memory for faster access.
    cache_session=True,
)

team.print_response("Tell me a new interesting fact about space")
