"""
Save Team to Database
=====================

Demonstrates creating a team with member agents and saving it to the database.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Member Agents
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
# Create the team
content_team = Team(
    id="content-team",
    name="Content Creation Team",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[researcher, writer],
    description="A team that researches and creates content",
    db=db,
)

# ---------------------------------------------------------------------------
# Run Team Save Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Save the team to the database
    version = content_team.save()
    print(f"Saved team as version {version}")

    # By default, saving a team will create a new version of the team

    # Delete the team from the database (soft delete by default)
    # content_team.delete()

    # Hard delete (permanently removes from database)
    # content_team.delete(hard_delete=True)
