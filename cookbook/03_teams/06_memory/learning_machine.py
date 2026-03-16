"""
Learning Machine
=============================

Demonstrates team learning with LearningMachine and user profile extraction.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
team_db = SqliteDb(db_file="tmp/teams.db")

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Collect user preference details and context.",
)

writer = Agent(
    name="Writer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Write concise recommendations tailored to the user.",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
learning_team = Team(
    name="Learning Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[researcher, writer],
    db=team_db,
    learning=LearningMachine(
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "team-learning-user"

    learning_team.print_response(
        "My name is Alex, and I prefer concise responses with bullet points.",
        user_id=user_id,
        session_id="learning_team_session_1",
        stream=True,
    )

    learning_team.print_response(
        "What do you remember about how I prefer responses?",
        user_id=user_id,
        session_id="learning_team_session_2",
        stream=True,
    )
