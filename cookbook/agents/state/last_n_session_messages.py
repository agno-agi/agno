import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# Remove the tmp db file before running the script
if os.path.exists("tmp/data.db"):
    os.remove("tmp/data.db")

# Create agents for different users to demonstrate user-specific session history
user_1_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    user_id="user_1",
    db=SqliteDb(db_file="tmp/data.db"),
    add_history_to_context=True,
    num_history_runs=3,
    search_session_history=True,  # allow searching previous sessions
    num_history_sessions=2,  # only include the last 2 sessions in the search to avoid context length issues
)

user_2_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    user_id="user_2",
    db=SqliteDb(db_file="tmp/data.db"),
    add_history_to_context=True,
    num_history_runs=3,
    search_session_history=True,
    num_history_sessions=2,
)

# User 1 sessions
print("=== User 1 Sessions ===")
user_1_agent.print_response(
    "What is the capital of South Africa?", session_id="user1_session_1"
)
user_1_agent.print_response(
    "What is the capital of China?", session_id="user1_session_2"
)
user_1_agent.print_response(
    "What is the capital of France?", session_id="user1_session_3"
)

# User 2 sessions
print("\n=== User 2 Sessions ===")
user_2_agent.print_response(
    "What is the population of India?", session_id="user2_session_1"
)
user_2_agent.print_response(
    "What is the currency of Japan?", session_id="user2_session_2"
)

# Now test session history search - each user should only see their own sessions
print("\n=== Testing Session History Search ===")
print(
    "User 1 asking about previous conversations (should only see capitals, not population/currency):"
)
user_1_agent.print_response(
    "What did I discuss in my previous conversations?", session_id="user1_session_4"
)

print(
    "\nUser 2 asking about previous conversations (should only see population/currency, not capitals):"
)
user_2_agent.print_response(
    "What did I discuss in my previous conversations?", session_id="user2_session_3"
)
