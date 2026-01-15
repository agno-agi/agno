"""
This cookbook demonstrates how to save a team to a PostgreSQL database.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.team.team import get_team_by_id, get_teams

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Define member agents
researcher = Agent(
    id="researcher-agent",
    name="Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Research and gather information",
)

writer = Agent(
    id="writer-agent",
    name="Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    role="Write content based on research",
)

# Create the team
content_team = Team(
    id="content-team",
    name="Content Creation Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, writer],
    description="A team that researches and creates content",
    db=db,
)

team = get_team_by_id(db=db, id="content-team")

# team.print_response("Write about the history of the internet.", stream=True)

teams = get_teams(db=db)
print(teams)
