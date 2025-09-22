"""This example shows how to use an in-memory database with teams.

With this you will be able to store team sessions, user memories, etc. without setting up a database.
Keep in mind that in production setups it is recommended to use a database.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from rich.pretty import pprint

# Setup the in-memory database
db = InMemoryDb()

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
    name="Research Assistant",
)

team = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[agent],
    db=db,
    # Set add_history_to_context=true to add the previous chat history to the context sent to the Model.
    add_history_to_context=True,
    # Number of historical responses to add to the messages.
    num_history_runs=3,
    session_id="test_session",
)

# -*- Create a run
team.print_response("Share a 2 sentence horror story", stream=True)

# -*- Print the messages in the memory
print("\n" + "=" * 50)
print("CHAT HISTORY AFTER FIRST RUN")
print("=" * 50)
try:
    chat_history = team.get_chat_history(session_id="test_session")
    pprint([m.model_dump(include={"role", "content"}) for m in chat_history])
except Exception as e:
    print(f"Error getting chat history: {e}")
    print("This might be expected on first run with in-memory database")

# -*- Ask a follow up question that continues the conversation
team.print_response("What was my first message?", stream=True)

# -*- Print the messages in the memory
print("\n" + "=" * 50)
print("CHAT HISTORY AFTER SECOND RUN")
print("=" * 50)
try:
    chat_history = team.get_chat_history(session_id="test_session")
    pprint([m.model_dump(include={"role", "content"}) for m in chat_history])
except Exception as e:
    print(f"Error getting chat history: {e}")
    print("This indicates an issue with in-memory database session handling")
