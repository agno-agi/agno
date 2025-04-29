from agno.agent import Agent
from agno.memory.v2 import Memory
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Multi-user, multi-session only work with Memory.V2
    memory=Memory(),
    add_history_to_messages=True,
    num_history_runs=3,
)

user_1_id = "user_101"
user_2_id = "user_102"

user_1_session_id = "session_101"
user_2_session_id = "session_102"

# Start the session with user 1
agent.print_response(
    "Tell me a 5 second short story about a robot.",
    user_id=user_1_id,
    session_id=user_1_session_id,
)
# Continue the session with user 1
agent.print_response(
    "Now tell me a joke.", user_id=user_1_id, session_id=user_1_session_id
)

# Start the session with user 2
agent.print_response(
    "Tell me about quantum physics.", user_id=user_2_id, session_id=user_2_session_id
)
# Continue the session with user 2
agent.print_response(
    "What is the speed of light?", user_id=user_2_id, session_id=user_2_session_id
)

# Ask the agent to give a summary of the conversation, this will use the history from the previous messages
agent.print_response(
    "Give me a summary of our conversation.",
    user_id=user_1_id,
    session_id=user_1_session_id,
)
