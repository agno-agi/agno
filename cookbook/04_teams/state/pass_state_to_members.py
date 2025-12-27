from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

agent = Agent(
    role="User Advisor",
    description="You answer questions related to the user.",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="User's name is {user_name} and age is {age}",
)

team = Team(
    db=InMemoryDb(),
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="You are a team that answers questions related to the user. Delegate to the member agent to address user requests or answer any questions about the user.",
    members=[agent],
    respond_directly=True,
)

# Sets the session state for the session with the id "session_1"
team.print_response(
    "Write a short poem about my name and age",
    session_id="session_1",
    user_id="user_1",
    session_state={"user_name": "John", "age": 30},
    add_session_state_to_context=True,
)

# Will load the session state from the session with the id "session_1"
team.print_response(
    "How old am I?",
    session_id="session_1",
    user_id="user_1",
    add_session_state_to_context=True,
)
