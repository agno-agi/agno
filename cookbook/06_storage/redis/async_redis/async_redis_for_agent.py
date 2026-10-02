"""
Example showing how to use Redis as the async database for an agent.

Run `uv pip install redis openai ddgs` to install the dependency.

We can start Redis locally using docker:
1. Start Redis container
`docker run --name my-redis -p 6379:6379 -d redis`

2. Verify container is running
`docker ps`

3. Run the file
`python cookbook/06_storage/redis/async_redis/async_redis_for_agent.py`
"""

import asyncio

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.redis import AsyncRedisDb
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = AsyncRedisDb(db_url="redis://localhost:6379")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    db=db,
    tools=[WebSearchTools()],
    add_history_to_context=True,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main():
    await agent.aprint_response("How many people live in Canada?")
    await agent.aprint_response("What is their national anthem called?")

    # Verify db contents
    print("\nVerifying db contents...")
    all_sessions = await db.get_sessions(session_type=SessionType.AGENT)
    print(f"Total sessions in Redis: {len(all_sessions)}")


if __name__ == "__main__":
    asyncio.run(main())
