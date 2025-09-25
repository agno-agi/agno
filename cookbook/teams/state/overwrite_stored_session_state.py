"""This example demonstrates how to overwrite the stored session_state with the session_state provided in the run."""

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# Create an Team that maintains state
team = Team(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=SqliteDb(db_file="tmp/agents.db"),
    members=[],
    markdown=True,
    # Set the default session_state. The values set here won't be overwritten.
    session_state={},
    # Adding the session_state to context for the agent to easily access it
    add_session_state_to_context=True,
    # Allow overwriting the stored session state with the session state provided in the run
    overwrite_db_session_state=True,
)

# Let's run the agent providing a session_state. This session_state will be stored in the database.
team.print_response(
    "Can you tell me what's in your session_state?",
    session_state={"shopping_list": ["Potatoes"]},
    stream=True,
)
print(f"Stored session state: {team.get_session_state()}")

# Now if we pass a new session_state, it will overwrite the stored session_state.
team.print_response(
    "Can you tell me what is in your session_state?",
    session_state={"secret_number": 43},
    stream=True,
)
print(f"Stored session state: {team.get_session_state()}")
