from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

team = Team(
    db=InMemoryDb(),
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[],
    instructions="Users name is {user_name} and age is {age}",
)

# Sets the session state for the session with the id "user_1_session_1"
team.print_response(
    "What is my name?",
    session_id="user_1_session_1",
    user_id="user_1",
    session_state={"user_name": "John", "age": 30},
)

# Will load the session state from the session with the id "user_1_session_1"
team.print_response("How old am I?", session_id="user_1_session_1", user_id="user_1")

# Sets the session state for the session with the id "user_2_session_1"
team.print_response(
    "What is my name?",
    session_id="user_2_session_1",
    user_id="user_2",
    session_state={"user_name": "Jane", "age": 25},
)

# Will load the session state from the session with the id "user_2_session_1"
team.print_response("How old am I?", session_id="user_2_session_1", user_id="user_2")
