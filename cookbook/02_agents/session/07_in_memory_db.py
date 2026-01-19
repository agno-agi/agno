"""This example shows how to use an in-memory database.

With this you will be able to store sessions, user memories, etc. without setting up a database.
Keep in mind that in production setups it is recommended to use a database.
"""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

# Setup the in-memory database
db = InMemoryDb()

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Use the in-memory database. All db features will be available.
    db=db,
    # Set add_history_to_context=true to add the previous chat history to the context sent to the Model.
    add_history_to_context=True,
    # Number of historical responses to add to the messages.
    num_history_runs=3,
    description="You are a helpful assistant that always responds in a polite, upbeat and positive manner.",
)

# -*- Create a run
agent.print_response("Share a 2 sentence horror story", stream=True)
# -*- Print the messages in the memory
pprint(
    [m.model_dump(include={"role", "content"}) for m in agent.get_session_messages()]
)

# -*- Ask a follow up question that continues the conversation
agent.print_response("What was my first message?", stream=True)
# -*- Print the messages in the memory
pprint(
    [m.model_dump(include={"role", "content"}) for m in agent.get_session_messages()]
)
