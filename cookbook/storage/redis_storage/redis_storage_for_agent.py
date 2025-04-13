"""
Test script for RedisStorage implementation.
Run `pip install redis duckduckgo-search openai` to install dependencies.

We can start Redis locally using docker:
1. Start Redis container
docker run --name my-redis -p 6379:6379 -d redis

2. Verify container is running
docker ps
"""

from agno.agent import Agent
from agno.storage.redis import RedisStorage
from agno.tools.duckduckgo import DuckDuckGoTools

# Initialize Redis storage with default local connection
storage = RedisStorage(prefix="agno_test", host="localhost", port=6379)

# Create agent with Redis storage
agent = Agent(
    storage=storage,
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)

agent.print_response("How many people live in Canada?")

agent.print_response("What is their national anthem called?")

# Verify storage contents
print("\nVerifying storage contents...")
all_sessions = storage.get_all_sessions()
print(f"Total sessions in Redis: {len(all_sessions)}")

if all_sessions:
    print("\nSession details:")
    session = all_sessions[0]
    print(f"Session ID: {session.session_id}")
    print(f"Messages count: {len(session.memory['messages'])}")
