"""
Example showing how to use Redis as the database for an agent.

Run `pip install redis ddgs openai` to install dependencies.

We can start Redis locally using docker:
1. Start Redis container
docker run --name my-redis -p 6379:6379 -d redis

2. Verify container is running
docker ps
"""

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.redis import RedisDb
from agno.tools.duckduckgo import DuckDuckGoTools

# Initialize Redis db (use the right db_url for your setup)
db = RedisDb(db_url="redis://localhost:6379")

# Create agent with Redis db
agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)

agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")

# Verify db contents
print("\nVerifying db contents...")
all_sessions = db.get_sessions(session_type=SessionType.AGENT)
print(f"Total sessions in Redis: {len(all_sessions)}")
