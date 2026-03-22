"""
Change State On Run
===================

Demonstrates per-run session state overrides for different users/sessions.
"""

from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    db=InMemoryDb(),
    model=OpenAIResponses(id="gpt-5.2"),
    members=[],
    instructions="Users name is {user_name} and age is {age}",
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response(
        "What is my name?",
        session_id="user_1_session_1",
        user_id="user_1",
        session_state={"user_name": "John", "age": 30},
    )

    team.print_response(
        "How old am I?",
        session_id="user_1_session_1",
        user_id="user_1",
    )

    team.print_response(
        "What is my name?",
        session_id="user_2_session_1",
        user_id="user_2",
        session_state={"user_name": "Jane", "age": 25},
    )

    team.print_response(
        "How old am I?",
        session_id="user_2_session_1",
        user_id="user_2",
    )
