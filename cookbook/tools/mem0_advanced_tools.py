from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mem0 import Mem0Tools

# Define a User ID for the session
USER_ID = "john_billings"
SESSION_ID = "session1"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[Mem0Tools()],
    user_id=USER_ID,
    session_id=SESSION_ID,
    add_state_in_messages=True,
    markdown=True,
    instructions=dedent(
        """
        You are a helpful assistant interacting with user: {current_user_id}.
        You MUST use the `Mem0Tools` which has gives you access to a bunch of tools to help you manage memories. The user's identifier is: {current_user_id}
        """
    ),
    show_tool_calls=True,
)

# User Alice, Session A1
agent.print_response(
    "My favorite hobby is painting.", user_id="alice", session_id="session_alice_1"
)
agent.print_response("What is my hobby?", user_id="alice", session_id="session_alice_1")

# New session for Alice: Session A2
agent.print_response(
    "I also enjoy hiking.", user_id="alice", session_id="session_alice_2"
)
agent.print_response(
    "What do you remember about my hobby?",
    user_id="alice",
    session_id="session_alice_1",
)

# User Bob, Session B1
agent.print_response("I love playing chess.", user_id="bob", session_id="session_bob_1")
agent.print_response("What games do I like?", user_id="bob", session_id="session_bob_1")

# Verify Alice's memories in Session A2
agent.print_response(
    "What is my favorite hobby?", user_id="alice", session_id="session_alice_2"
)

# List all memories for Bob
agent.print_response("List all my memories.", user_id="bob", session_id="session_bob_1")

# Delete Bob's memories
agent.print_response(
    "Forget everything about me.", user_id="bob", session_id="session_bob_1"
)
agent.print_response("I like dogs.", user_id="bob", session_id="session_bob_2")
agent.print_response(
    "What do you know about me now?", user_id="bob", session_id="session_bob_2"
)
