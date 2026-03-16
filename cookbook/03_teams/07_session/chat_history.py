"""
Chat History
=============================

Demonstrates retrieving chat history and limiting included history messages.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="sessions")

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
agent = Agent(model=OpenAIResponses(id="gpt-5-mini"))

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
history_team = Team(
    model=OpenAIResponses(id="gpt-5-mini"),
    members=[agent],
    db=db,
)

limited_history_team = Team(
    model=OpenAIResponses(id="gpt-5.2"),
    members=[Agent(model=OpenAIResponses(id="gpt-5.2"))],
    db=db,
    add_history_to_context=True,
    num_history_messages=1,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    history_team.print_response("Tell me a new interesting fact about space")
    print(history_team.get_chat_history())

    history_team.print_response("Tell me a new interesting fact about oceans")
    print(history_team.get_chat_history())

    limited_history_team.print_response("Tell me a new interesting fact about space")
    limited_history_team.print_response(
        "Repeat the last message, but make it much more concise"
    )
