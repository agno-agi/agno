"""
Learning Machine
=============================

Learning Machine.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
agent_db = SqliteDb(db_file="tmp/agents.db")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Learning Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    db=agent_db,
    learning=LearningMachine(
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "learning-demo-user"

    agent.print_response(
        "My name is Alex, and I prefer concise responses.",
        user_id=user_id,
        session_id="learning_session_1",
        stream=True,
    )

    agent.print_response(
        "What do you remember about me?",
        user_id=user_id,
        session_id="learning_session_2",
        stream=True,
    )
