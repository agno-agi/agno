"""Async Memory V2 - Concurrent users with personalized memory.

Demonstrates async support for Memory V2:
- Async automatic learning with arun()
- Async agentic memory tools
- Concurrent user conversations with asyncio.gather()

Run: pip install aiosqlite
"""

import asyncio
import json

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.models.openai import OpenAIChat
from rich import print_json

DB_FILE = "tmp/async_user_memory2.db"
ALEX_ID = "alex"
JORDAN_ID = "jordan"

db = AsyncSqliteDb(db_file=DB_FILE)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    enable_agentic_memory_v2=True,
    markdown=True,
)


async def alex_conversation():
    await agent.arun(
        "Hi! I'm Alex, a backend developer. I work primarily with Python and FastAPI.",
        user_id=ALEX_ID,
    )
    await agent.arun(
        "I always use type hints in my Python code. Please include them in any examples.",
        user_id=ALEX_ID,
    )
    await agent.arun(
        "We use PostgreSQL for our database and Redis for caching.",
        user_id=ALEX_ID,
    )
    await agent.arun(
        "Please remember that I prefer async/await patterns over threading.",
        user_id=ALEX_ID,
    )


async def jordan_conversation():
    await agent.arun(
        "Hey! I'm Jordan, a frontend developer. I specialize in React and TypeScript.",
        user_id=JORDAN_ID,
    )
    await agent.arun(
        "I prefer functional components with hooks over class components.",
        user_id=JORDAN_ID,
    )
    await agent.arun(
        "Our frontend uses Vite for bundling and React Query for server state.",
        user_id=JORDAN_ID,
    )
    await agent.arun(
        "Remember that I like seeing accessibility considerations in UI code.",
        user_id=JORDAN_ID,
    )


async def main():
    await asyncio.gather(alex_conversation(), jordan_conversation())

    print("\n[Alex's Memory]")
    alex_profile = await agent.aget_user_memory_v2(ALEX_ID)
    if alex_profile:
        print_json(json.dumps(alex_profile.to_dict()))

    print("\n[Jordan's Memory]")
    jordan_profile = await agent.aget_user_memory_v2(JORDAN_ID)
    if jordan_profile:
        print_json(json.dumps(jordan_profile.to_dict()))

    print("\n[Personalized responses]")
    await agent.aprint_response(
        "What's the best way to handle API errors?", user_id=ALEX_ID, stream=True
    )
    await agent.aprint_response(
        "What's the best way to handle API errors?", user_id=JORDAN_ID, stream=True
    )


if __name__ == "__main__":
    asyncio.run(main())
