"""
Overwrite Stored Session State
==============================

Demonstrates replacing persisted session_state with run-time session_state.
"""

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    model=OpenAIResponses(id="gpt-5.2"),
    db=SqliteDb(db_file="tmp/agents.db"),
    members=[],
    markdown=True,
    session_state={},
    add_session_state_to_context=True,
    overwrite_db_session_state=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    team.print_response(
        "Can you tell me what's in your session_state?",
        session_state={"shopping_list": ["Potatoes"]},
        stream=True,
    )
    print(f"Stored session state: {team.get_session_state()}")

    team.print_response(
        "Can you tell me what is in your session_state?",
        session_state={"secret_number": 43},
        stream=True,
    )
    print(f"Stored session state: {team.get_session_state()}")
